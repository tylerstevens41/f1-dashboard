"""Version-pinned transport seam: preserve raw snapshot/delta topic shapes."""
from livef1.adapters.realtime_client import RealF1Client
from .protocol import TOPICS


class DashboardClient(RealF1Client):
    def __init__(self, emit, status, snapshot=None):
        super().__init__(topics=list(TOPICS))
        self.snapshot = snapshot
        self.emit = emit
        self.status = status

    async def _stream(self, force_login):
        await self.status('connecting')
        try:
            async for marker in super()._stream(force_login):
                await self.status('connected')
                yield marker
        finally:
            await self.status('disconnected')

    async def _dispatch(self, frame):
        # RealF1Client's standard handler cannot parse TimingAppData (None in
        # function_map in 1.3.0). Keep all uncompressed fields/index deltas raw.
        if frame.get('type') == 3:
            if frame.get('error'):
                await self.status('subscription-error')
                return
            if self.snapshot:
                await self.snapshot()
            for topic, payload in (frame.get('result') or {}).items():
                await self.emit(topic, payload, None)
        elif frame.get('target') == 'feed':
            args = frame.get('arguments') or []
            if len(args) >= 2:
                await self.emit(args[0], args[1], args[2] if len(args) > 2 else None)
