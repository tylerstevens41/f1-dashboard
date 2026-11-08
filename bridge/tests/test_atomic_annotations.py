"""Regression for the real Windows sectors-checkpoint replace failure."""
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
from bridge.annotation_progress import atomic
from bridge.diagnostics import safe_exception


def locked(code=32):
    error=PermissionError('PRIVATE destination path')
    error.winerror=code
    return error


class AtomicAnnotationTests(TestCase):
    def test_transient_windows_lock_retries_without_deleting_old_file(self):
        import os
        real_replace=os.replace
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'output.json';atomic(target,{'old':True})
            attempts=[]
            def replace(source,destination):
                attempts.append(1)
                self.assertEqual(json.loads(target.read_text()),{'old':True})
                self.assertEqual(json.loads(Path(source).read_text()),{'new':True})
                if len(attempts)<3:raise locked()
                real_replace(source,destination)
            with patch('bridge.annotation_progress.os.replace',side_effect=replace),patch('bridge.annotation_progress.time.sleep') as sleep:
                atomic(target,{'new':True})
            self.assertEqual(len(attempts),3);self.assertEqual(sleep.call_count,2)
            self.assertEqual(json.loads(target.read_text()),{'new':True})
            self.assertEqual(list(Path(temp).glob('.annotation-*')),[])

    def test_persistent_windows_lock_has_bounded_retries_and_preserves_target(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'output.json';atomic(target,{'old':True})
            with patch('bridge.annotation_progress.os.replace',side_effect=locked(5)) as replace,patch('bridge.annotation_progress.time.sleep') as sleep:
                with self.assertRaises(PermissionError) as caught:atomic(target,{'new':True})
            self.assertEqual(replace.call_count,6);self.assertEqual(sleep.call_count,5)
            self.assertEqual(json.loads(target.read_text()),{'old':True})
            self.assertEqual(list(Path(temp).glob('.annotation-*')),[])
            report=safe_exception(caught.exception,'annotations')
            self.assertEqual(report['windowsErrorCode'],5);self.assertNotIn('PRIVATE',str(report))

    def test_other_permissions_are_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('bridge.annotation_progress.os.replace',side_effect=PermissionError('denied')) as replace,patch('bridge.annotation_progress.time.sleep') as sleep:
                with self.assertRaises(PermissionError):atomic(Path(temp)/'output.json',{})
            self.assertEqual(replace.call_count,1);sleep.assert_not_called()

    def test_circuit_revision_writer_uses_same_bounded_lock_recovery(self):
        import os
        from bridge.preparation import atomic_json
        original=os.replace
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'current.json';atomic_json(target,{'revision':'old'})
            attempts=[]
            def replace(source,destination):
                attempts.append(1)
                if len(attempts)==1:raise locked(32)
                original(source,destination)
            with patch('bridge.annotation_progress.os.replace',side_effect=replace),patch('bridge.annotation_progress.time.sleep'):
                atomic_json(target,{'revision':'new'})
            self.assertEqual(len(attempts),2)
            self.assertEqual(json.loads(target.read_text()),{'revision':'new'})
