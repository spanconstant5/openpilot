import ast
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class TestSafetyContract(unittest.TestCase):
  def test_daemon_has_no_transmit_surface(self):
    source = "\n".join(
      (PACKAGE_ROOT / filename).read_text(encoding="utf-8")
      for filename in ("daemon.py", "session.py", "discovery.py")
    )
    tree = ast.parse(source)
    imported = {
      alias.name
      for node in ast.walk(tree)
      if isinstance(node, (ast.Import, ast.ImportFrom))
      for alias in node.names
    }
    called = {
      node.func.id
      for node in ast.walk(tree)
      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    banned = {"PubMaster", "pub_sock", "sendcan", "can_send", "can_list_to_can_capnp"}
    self.assertTrue(banned.isdisjoint(imported))
    self.assertTrue(banned.isdisjoint(called))
    self.assertTrue(banned.isdisjoint(attributes))
    for name in banned:
      self.assertNotIn(name, source)

  def test_manager_registration_is_onroad_and_restartable(self):
    config = (REPOSITORY_ROOT / "openpilot/system/manager/process_config.py").read_text(encoding="utf-8")
    expected = " ".join((
      'PythonProcess("tss3cruiseprobed", "openpilot.system.tss3_cruise_recorder.daemon",',
      "only_onroad, restart_if_crash=True)",
    ))
    self.assertIn(expected, config)


if __name__ == "__main__":
  unittest.main()
