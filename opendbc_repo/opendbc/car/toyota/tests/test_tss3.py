from opendbc.car.toyota.e2e import apply_e2e_160, e2e_160_valid
from opendbc.car.toyota.toyotacan import modify_tss3_160


def test_e2e_rejects_wrong_size():
  try:
    apply_e2e_160(bytes(31))
  except ValueError:
    pass
  else:
    raise AssertionError("non-32-byte 0x160 payload was accepted")


def test_modify_160_preserves_unknown_bytes_and_updates_crc():
  template = apply_e2e_160(bytes(range(32)), counter=41)
  msg = modify_tss3_160(template, -1.5, 10.0, 42)

  assert msg.address == 0x160
  assert msg.src == 0
  assert len(msg.dat) == 32
  assert msg.dat[2] == 42
  assert e2e_160_valid(msg.dat)
  assert msg.dat[4:6] == bytes((0x7A, 0x24))
  assert int.from_bytes(msg.dat[22:24], "big", signed=True) == 5377
  assert msg.dat[3] == template[3]
  assert msg.dat[6:22] == template[6:22]
  assert msg.dat[24:] == template[24:]


def test_modify_160_relay_keeps_accel_and_steer():
  template = apply_e2e_160(bytes(range(32)), counter=9)
  msg = modify_tss3_160(template, None, None, 9)
  assert msg.dat == template
