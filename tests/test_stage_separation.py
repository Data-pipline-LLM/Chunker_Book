import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from api import main as chunker_api


class ChunkerStageSeparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_root_patch = patch.object(chunker_api, 'DATA_ROOT', self.root)
        self.data_root_patch.start()
        self.addCleanup(self.data_root_patch.stop)
        self.job_id = str(uuid.uuid4())
        paths = chunker_api.paths_for(self.job_id)
        paths['source'].parent.mkdir(parents=True, exist_ok=True)
        paths['source'].write_bytes(b'%PDF-1.7 test')
        chunker_api.atomic_write_json(paths['status'], {
            'job_id': self.job_id,
            'filename': 'book.pdf',
            'input_type': 'pdf',
            'controlled': True,
            'stage_mode': 'ocr-only',
            'status': 'queued',
            'stage': 'queued',
            'progress': 0,
        })

    def test_ocr_only_job_returns_before_semantic_chunking(self):
        ocr_result = {
            'pages': [
                {'page_no': 1, 'cells': [{'category': 'Text', 'text': 'نمونه متن فارسی'}]},
            ],
        }
        with patch.object(chunker_api, 'call_ocr', return_value=ocr_result), \
             patch.object(chunker_api, 'run_chunker', side_effect=AssertionError('Chunker must not run')):
            chunker_api.run_job(self.job_id)

        status = chunker_api.read_status(self.job_id)
        self.assertEqual(status['status'], 'completed')
        self.assertEqual(status['stage'], 'ocr_completed')
        self.assertEqual(status['result']['page_count'], 1)
        self.assertTrue(chunker_api.paths_for(self.job_id)['ocr_raw'].is_file())
        self.assertTrue(chunker_api.paths_for(self.job_id)['ocr_normalized'].is_file())

    def test_controlled_ocr_and_ocr_json_jobs_use_independent_executors(self):
        with patch.object(chunker_api.OCR_EXECUTOR, 'submit') as ocr_submit:
            chunker_api._submit_job(self.job_id, {'stage_mode': 'ocr-only', 'input_type': 'pdf'})
            ocr_submit.assert_called_once_with(chunker_api.run_job, self.job_id)

        with patch.object(chunker_api.CHUNKER_EXECUTOR, 'submit') as chunker_submit:
            chunker_api._submit_job(self.job_id, {'stage_mode': 'full', 'input_type': 'ocr_json'})
            chunker_submit.assert_called_once_with(chunker_api.run_job, self.job_id)


if __name__ == '__main__':
    unittest.main()
