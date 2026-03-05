"""Binance WS feeds for BTC/ETH/SOL/XRP."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

import ujson
import websockets

from core.event_bus import bus
from core.logger import logger
from core.state import state

WS_URL = 'wss://stream.binance.com:9443/ws'

ASSETS = {
    'BTC': 'btcusdt@trade',
    'ETH': 'ethusdt@trade',
    'SOL': 'solusdt@trade',
    'XRP': 'xrpusdt@trade',
}


@dataclass
class _KalmanL2:
    """2-state (position, velocity) Kalman filter."""

    x0: float = 0.0
    x1: float = 0.0
    p00: float = 1000.0
    p01: float = 0.0
    p10: float = 0.0
    p11: float = 1000.0
    q: float = 0.1
    r: float = 0.01
    _init: bool = False

    def update(self, z: float, dt: float) -> tuple[float, float]:
        if not self._init:
            self.x0 = z
            self._init = True
            return self.x0, self.x1
        dt = max(dt, 1e-6)
        xp0 = self.x0 + self.x1 * dt
        xp1 = self.x1
        q = self.q
        pp00 = self.p00 + dt * (self.p10 + self.p01) + dt * dt * self.p11 + q * dt ** 4 / 4
        pp01 = self.p01 + dt * self.p11 + q * dt ** 3 / 2
        pp10 = self.p10 + dt * self.p11 + q * dt ** 3 / 2
        pp11 = self.p11 + q * dt * dt
        s = pp00 + self.r
        k0 = pp00 / s
        k1 = pp10 / s
        y = z - xp0
        self.x0 = xp0 + k0 * y
        self.x1 = xp1 + k1 * y
        self.p00 = (1 - k0) * pp00
        self.p01 = (1 - k0) * pp01
        self.p10 = pp10 - k1 * pp00
        self.p11 = pp11 - k1 * pp01
        return self.x0, self.x1


@dataclass
class AssetBuffer:
    prices: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    volumes: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    sides: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    accelerations: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    _vwap_pv: float = 0.0
    _vwap_v: float = 0.0
    _vwap_count: int = 0
    _kalman: _KalmanL2 = field(default_factory=_KalmanL2)
    _last_ts: float = 0.0

    def push(self, price: float, volume: float, ts: float, side: str) -> None:
        dt = ts - self._last_ts if self._last_ts else 0.0
        self._last_ts = ts
        self.prices.append(price)
        self.volumes.append(volume)
        self.timestamps.append(ts)
        self.sides.append(side)
        self._vwap_pv += price * volume
        self._vwap_v += volume
        self._vwap_count += 1
        if self._vwap_count % 10000 == 0:
            self._vwap_pv = price * volume
            self._vwap_v = volume
        self._kalman.update(price, dt)

    # -- public API matching spec -----------------------------------------

    def vel(self, secs: float) -> float:
        if len(self.prices) < 2 or not self.timestamps:
            return 0.0
        p_ago = self._price_ago(secs)
        return (self.prices[-1] - p_ago) / secs if p_ago else 0.0

    def vol_ratio(self, short: float, long: float) -> float:
        vs = self._avg_vol(short)
        vl = self._avg_vol(long)
        return vs / vl if vl else 1.0

    def buy_pct(self, secs: float = 30) -> float:
        if not self.timestamps:
            return 0.5
        cutoff = self.timestamps[-1] - secs
        matched = [s for s, t in zip(self.sides, self.timestamps) if t >= cutoff]
        if not matched:
            return 0.5
        return sum(1 for s in matched if s == 'BUY') / len(matched)

    def rsi(self, period: int = 14) -> float:
        if len(self.prices) < period + 1:
            return 50.0
        gains = 0.0
        losses = 0.0
        for i in range(-period, 0):
            d = self.prices[i] - self.prices[i - 1]
            if d > 0:
                gains += d
            else:
                losses += abs(d)
        ag = gains / period
        al = losses / period if losses else 1e-9
        rs = ag / al
        return 100 - (100 / (1 + rs))

    def vwap(self) -> float:
        if self._vwap_v <= 0:
            return self.prices[-1] if self.prices else 0.0
        return self._vwap_pv / self._vwap_v

    def consec(self) -> int:
        if len(self.prices) < 2:
            return 0
        px = list(self.prices)[-50:]
        direction = 1 if px[-1] > px[-2] else -1
        count = 0
        for i in range(len(px) - 1, 0, -1):
            d = 1 if px[i] > px[i - 1] else -1
            if d == direction:
                count += direction
            else:
                break
        return count

    # -- internal helpers -------------------------------------------------

    def _price_ago(self, secs: float) -> float:
        if not self.timestamps:
            return 0.0
        tgt = self.timestamps[-1] - secs
        for i in range(len(self.timestamps) - 1, -1, -1):
            if self.timestamps[i] <= tgt:
                return self.prices[i]
        return self.prices[0]

    def _avg_vol(self, secs: float) -> float:
        if not self.timestamps:
            return 0.0
        cutoff = self.timestamps[-1] - secs
        vals = [v for v, t in zip(self.volumes, self.timestamps) if t >= cutoff]
        return sum(vals) / len(vals) if vals else 0.0

    def metrics(self) -> dict[str, float]:
        if len(self.prices) < 3:
            return {
                'velocity_10s': 0.0, 'velocity_30s': 0.0, 'velocity_60s': 0.0, 'velocity_300s': 0.0,
                'acceleration': 0.0, 'jerk': 0.0, 'volume_ratio_10_60': 1.0, 'volume_ratio_60_300': 1.0,
                'buy_volume_pct': 0.5, 'rsi_14': 50.0, 'vwap_deviation': 0.0, 'consecutive_direction': 0,
                'pct_change_60s': 0.0, 'kalman_price': 0.0, 'kalman_velocity': 0.0,
            }
        p = self.prices[-1]
        v10 = self.vel(10)
        v30 = self.vel(30)
        v60 = self.vel(60)
        v300 = self.vel(300)
        accel = v10 - v30
        self.accelerations.append(accel)
        jerk = accel - self.accelerations[-6] if len(self.accelerations) > 6 else 0.0
        vw = self.vwap()
        return {
            'velocity_10s': v10,
            'velocity_30s': v30,
            'velocity_60s': v60,
            'velocity_300s': v300,
            'acceleration': accel,
            'jerk': jerk,
            'volume_ratio_10_60': self.vol_ratio(10, 60),
            'volume_ratio_60_300': self.vol_ratio(60, 300),
            'buy_volume_pct': self.buy_pct(30),
            'rsi_14': self.rsi(14),
            'vwap_deviation': ((p - vw) / vw) if vw else 0.0,
            'consecutive_direction': self.consec(),
            'pct_change_60s': (v60 * 60 / p) if p else 0.0,
            'kalman_price': self._kalman.x0,
            'kalman_velocity': self._kalman.x1,
        }


class BinanceFeed:
    def __init__(self) -> None:
        self.buffers = {a: AssetBuffer() for a in ASSETS}

    async def _run_asset(self, asset: str, stream: str) -> None:
        url = f'{WS_URL}/{stream}'
        backoff = 0.1
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    await state.set(f'feed.binance.{asset}.connected', True)
                    await state.set(f'feed.binance.{asset}.last_tick', time.time())
                    await bus.publish('FEED_RECONNECTED', {'feed': 'binance', 'asset': asset})
                    backoff = 0.1
                    async for raw in ws:
                        data = ujson.loads(raw)
                        px = float(data.get('p', 0.0))
                        vol = float(data.get('q', 0.0))
                        ts = float(data.get('T', int(time.time() * 1000))) / 1000
                        side = 'SELL' if data.get('m', False) else 'BUY'

                        buf = self.buffers[asset]
                        buf.push(px, vol, ts, side)
                        m = buf.metrics()

                        await state.set(f'price.{asset}.price', px)
                        await state.set(f'price.{asset}.timestamp', ts)
                        for k, v in m.items():
                            await state.set(f'price.{asset}.{k}', v)
                        await state.set(f'feed.binance.{asset}.last_tick', time.time())
                        state.append_list(f'history.{asset}.velocity_60s', float(m['velocity_60s']), maxlen=1800)

                        payload = {'asset': asset, 'price': px, 'volume': vol, 'timestamp': ts, 'side': side, **m}
                        await bus.publish('PRICE_TICK', payload)
                        if abs(float(m['pct_change_60s'])) > 0.003:
                            await bus.publish('MAJOR_MOVE', payload)
                        if float(m['volume_ratio_10_60']) > 3.0:
                            await bus.publish('VOLUME_SPIKE', payload)
                        if abs(float(m['acceleration'])) > 0.0004 and (float(m['acceleration']) * float(m['velocity_30s'])) < 0:
                            await bus.publish('VELOCITY_REVERSAL', payload)
            except Exception as exc:  # noqa: BLE001
                await state.set(f'feed.binance.{asset}.connected', False)
                await bus.publish('FEED_DISCONNECTED', {'feed': 'binance', 'asset': asset, 'error': str(exc)})
                logger.warning('binance_reconnect', asset=asset, sleep=backoff, error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)

    async def run(self) -> None:
        await asyncio.gather(*[self._run_asset(a, s) for a, s in ASSETS.items()])


async def start_binance_feeds() -> None:
    await BinanceFeed().run()
