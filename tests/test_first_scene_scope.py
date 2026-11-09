import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.scene_design import scene_references
from src.shared import workflow
from src.shared._workflow_store import WorkflowError
from src.shared.review import record_review


class FirstSceneScopeTests(unittest.TestCase):
    def test_workflow_dispatches_only_first_scene(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workflow.create_project(root, 'Example')
            script = root / 'script.md'
            script.write_text('Example narration')
            workflow.submit_artifact(root, 'script', 'v001', script, scene_ids=['s1', 's2'])
            record_review(root, 'script', 'v001', 'approve')
            with patch('src.scene_design.scene_generation.run_scenes', return_value={'ok': True}) as generate:
                self.assertEqual(workflow.run_workflow(root, ai=True), {'ok': True})
                self.assertEqual(generate.call_args.kwargs['scene_id'], 's1')
                with self.assertRaises(WorkflowError) as error:
                    workflow.run_workflow(root, ai=True, scene_id='s2')
                self.assertEqual(error.exception.code, 'FIRST_SCENE_ONLY')
                with self.assertRaises(WorkflowError) as error:
                    workflow.run_workflow(root, ai=True, scene_id='s1', auto_continue=True)
                self.assertEqual(error.exception.code, 'FIRST_SCENE_ONLY')
                self.assertEqual(generate.call_count, 1)

    def test_lookup_reads_requested_api_from_local_0221_reference(self):
        def inspect(names):
            return {name: {'available': True, 'module': 'manim' if name == 'Circle' else 'manim_kit'} for name in names}
        with patch.object(scene_references, '_inspect', side_effect=inspect):
            result = scene_references.lookup(['Circle'], [])
        paths = [item['path'] for item in result['references']]
        self.assertTrue(any(path.startswith('manim-0.22.1/') and path.endswith('/Circle.md') for path in paths))
        self.assertTrue(all(item['content'] for item in result['references']))


if __name__ == '__main__':
    unittest.main()
