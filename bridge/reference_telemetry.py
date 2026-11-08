"""Public FastF1 telemetry access with explicit readiness and lap fallback."""
import logging
import numpy as np
from .corner_import import ImportFailure


class TelemetryUnavailable(ImportFailure):
    code='fastf1-telemetry-unavailable'


class TelemetryFailureCapture(logging.Handler):
    """Capture the exception object, never format/export library log messages."""
    def __init__(self):
        super().__init__();self.failure=None
    def emit(self,record):
        if record.msg=='Traceback for failure in telemetry data' and record.exc_info:
            self.failure=record.exc_info[1]


def load_positions(session,notify):
    logger=logging.getLogger('fastf1.core')
    previous=logger.level
    capture=TelemetryFailureCapture()
    logger.addHandler(capture);logger.setLevel(logging.DEBUG)
    try:
        # Documented public sequence: reuse loaded laps and load car/position
        # data with FastF1's own t0_date and LapStartDate processing.
        session.load(laps=False,telemetry=True,weather=False,messages=False)
        def ready():
            positions=session.pos_data
            clock=session.t0_date
            usable=sum(1 for frame in positions.values() if not frame.empty and {'X','Y','SessionTime'}.issubset(frame.columns))
            notify('telemetry-readiness',positionDrivers=len(positions),usablePositionDrivers=usable)
            if clock is None or not usable:raise TelemetryUnavailable('Session has no usable position telemetry or source clock')
        notify('telemetry-readiness')
        try:ready()
        except Exception:
            # One supported complete public load repairs stale/partial session
            # state if possible, using FastF1's cache and unchanged clock math.
            # Never retry indefinitely or manufacture the missing properties.
            original=capture.failure
            notify('telemetry-full-reload')
            session.load(laps=True,telemetry=True,weather=False,messages=False)
            notify('telemetry-readiness')
            try:ready()
            except Exception:
                if capture.failure is not None:raise capture.failure from None
                if original is not None:raise original from None
                raise TelemetryUnavailable('Position telemetry remains unavailable after a complete public session load') from None
    finally:
        logger.removeHandler(capture);logger.setLevel(previous)


def reference_positions(session,notify):
    """Keep the existing fastest lap when usable, then try timed non-pit laps.

    All coordinates remain measured get_pos_data samples; no clock reassignment,
    session rebinding, private data mutation or interpolation is introduced.
    """
    first=session.laps.pick_fastest()
    if first is None:raise ImportFailure('No reference lap available')
    rejected=0
    seen=set()
    def candidates():
        yield first
        laps=session.laps.pick_accurate().pick_quicklaps().pick_wo_box().sort_values('LapTime')
        for _,lap in laps.iterlaps():yield lap
    for lap in candidates():
        identity=(str(lap.DriverNumber),int(lap.LapNumber))
        if identity in seen:continue
        seen.add(identity)
        try:
            if lap.session is not session:raise TelemetryUnavailable('Reference lap is bound to a different session')
            pos=lap.get_pos_data()[['X','Y']].dropna()
            values=pos.to_numpy().astype(float)
            if len(values)<100 or not np.isfinite(values).all() or np.ptp(values,axis=0).max()<=0:
                raise TelemetryUnavailable('Reference lap has insufficient finite moving positions')
        except (KeyError,ValueError,TelemetryUnavailable) as exc:
            rejected+=1
            notify('reference-lap-position',rejected=rejected)
            continue
        except Exception as exc:
            # DataNotLoadedError is library-specific; do not swallow unrelated
            # exceptions or programming errors while selecting a fallback lap.
            from fastf1.exceptions import DataNotLoadedError
            if not isinstance(exc,DataNotLoadedError):raise
            rejected+=1;notify('reference-lap-position',rejected=rejected)
            continue
        notify('reference-lap-position',accepted=1,rejected=rejected)
        return lap,pos
    raise TelemetryUnavailable('No valid reference lap has accessible position telemetry')
