# Simulation bench

The droids bridge sends commands to a Boston Dynamics Spot. The emulator accepts or refuses commands the way the client library does and tracks a session, so the transport, the session handling and the platform profiles run without a robot.

The simulation bench replaces the hardware with a bosdyn-client-shaped Spot (`tests/spot_emulator.py`) on the command builder and sink seams of the real transport. It proves the parsing, the gating, the transports and the failure paths of the bridge; it says nothing about
a real machine, real timing or real safety functions.

## Run it

```
python -m unittest -v <modules>
```

from the `tests` folder, with `src` of this repository and `clients/python/src` of the SDK on `PYTHONPATH` (the same layout `python tools/build_test.py` uses). The
workflow named "Simulation bench" does exactly this on a clean Linux runner on every push and pull request, by hand and once a week, with nothing but Python.

## What it runs

| File | What it exercises |
|------|-------------------|
| `tests/test_spot_emulator.py` | the emulator: accepted and refused commands |
| `tests/test_spot_session.py` | session bring-up with a fake emergency stop, lease, power and state |
| `tests/test_spot_transport.py` | the real transport against the emulator |
| `tests/test_coordinator.py` | the coordinator and its gate |
| `tests/test_mqtt_transport.py` | the topic dispatch, QoS, idempotency and limits without a broker |

The broker scenarios start a real MQTT broker from a checkout of HYDRA-UMC-MQTT-BROKER (`HYDRA_UMC_TEST_BROKER_DIR`); the simulation job does not install it, so
those cases skip themselves there and run in the normal test run on a machine that has the broker.

## What it cannot show

A real Spot, the real client library and its authentication, a real lease and the behaviour of the robot on a floor. The hardware row of the status table therefore stays at "simulated" until a person has run the bridge on a real setup.
