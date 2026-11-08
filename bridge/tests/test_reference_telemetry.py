import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
import numpy as np
import pandas as pd
from bridge.reference_telemetry import load_positions,reference_positions,TelemetryUnavailable
from bridge.diagnostics import safe_exception


class ReferenceTelemetryTests(TestCase):
    def test_parsed_but_uninitialized_reports_original_soft_failure(self):
        class Session:
            def load(self,**kwargs):
                try:raise ValueError('PRIVATE upstream data')
                except ValueError:
                    logging.getLogger('fastf1.core').debug('Traceback for failure in telemetry data',exc_info=True)
            @property
            def pos_data(self):raise RuntimeError('DataNotLoadedError')
        before=logging.getLogger('fastf1.core').level
        with self.assertRaisesRegex(ValueError,'PRIVATE') as caught:load_positions(Session(),Mock())
        self.assertNotIn('PRIVATE',str(safe_exception(caught.exception,'annotations')))
        self.assertEqual(logging.getLogger('fastf1.core').level,before)

    def test_public_two_stage_load_and_readiness(self):
        session=SimpleNamespace(load=Mock(),pos_data={'1':pd.DataFrame({'X':[1],'Y':[2],'SessionTime':[0]})},t0_date=pd.Timestamp('2026-01-01'))
        progress=Mock();load_positions(session,progress)
        session.load.assert_called_once_with(laps=False,telemetry=True,weather=False,messages=False)
        progress.assert_called_with('telemetry-readiness',positionDrivers=1,usablePositionDrivers=1)

    def test_empty_or_missing_clock_is_explicit(self):
        for positions,clock in [({},None),({'1':pd.DataFrame()},pd.Timestamp('2026-01-01'))]:
            with self.assertRaises(TelemetryUnavailable):load_positions(SimpleNamespace(load=Mock(),pos_data=positions,t0_date=clock),Mock())

    def fixture(self):
        positions=pd.DataFrame(np.column_stack([np.arange(110),np.arange(110)**2]),columns=['X','Y'])
        session=SimpleNamespace()
        lap=SimpleNamespace(DriverNumber='1',LapNumber=3,session=session,get_pos_data=Mock(return_value=positions))
        session.laps=SimpleNamespace(pick_fastest=lambda:lap)
        return session,lap,positions

    def test_fastest_usable_lap_is_unchanged(self):
        session,lap,pos=self.fixture()
        actual,coordinates=reference_positions(session,Mock())
        self.assertIs(actual,lap);pd.testing.assert_frame_equal(coordinates,pos)

    def test_missing_preferred_lap_uses_real_alternative(self):
        session,first,positions=self.fixture()
        class DataNotLoadedError(Exception):pass
        first.get_pos_data.side_effect=DataNotLoadedError('PRIVATE')
        second=SimpleNamespace(DriverNumber='2',LapNumber=5,session=session,get_pos_data=Mock(return_value=positions))
        alternatives=Mock();alternatives.pick_quicklaps.return_value.pick_wo_box.return_value.sort_values.return_value.iterlaps.return_value=iter([(0,first),(1,second)])
        session.laps.pick_accurate=lambda:alternatives
        with patch.dict('sys.modules',{'fastf1.exceptions':SimpleNamespace(DataNotLoadedError=DataNotLoadedError)}):
            lap,pos=reference_positions(session,Mock())
        self.assertIs(lap,second);pd.testing.assert_frame_equal(pos,positions)

    def test_no_usable_lap_or_wrong_session_fails_without_fake_coordinates(self):
        session,lap,_=self.fixture();lap.session=object()
        alternatives=Mock();alternatives.pick_quicklaps.return_value.pick_wo_box.return_value.sort_values.return_value.iterlaps.return_value=iter([])
        session.laps.pick_accurate=lambda:alternatives
        with self.assertRaises(TelemetryUnavailable):reference_positions(session,Mock())

    def test_full_public_load_recovers_partial_session(self):
        session=SimpleNamespace(pos_data={},t0_date=None)
        def load(**kwargs):
            if kwargs['laps']:
                session.pos_data={'1':pd.DataFrame({'X':[1],'Y':[2],'SessionTime':[0]})}
                session.t0_date=pd.Timestamp('2026-01-01')
        session.load=Mock(side_effect=load)
        load_positions(session,Mock())
        self.assertEqual(session.load.call_args_list[1].kwargs,dict(laps=True,telemetry=True,weather=False,messages=False))

    def test_installed_fastf1_unloaded_position_property(self):
        try:
            from fastf1.core import Session
            from fastf1.exceptions import DataNotLoadedError
        except ImportError:self.skipTest('FastF1 only installed in dedicated environment')
        session=Session.__new__(Session)
        with self.assertRaises(DataNotLoadedError):_ = session.pos_data
        session.load=Mock()
        with self.assertRaises(TelemetryUnavailable):load_positions(session,Mock())
        self.assertEqual(session.load.call_count,2)
