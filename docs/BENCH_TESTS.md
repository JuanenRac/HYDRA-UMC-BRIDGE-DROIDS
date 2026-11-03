# Bench tests

Every test below is **not executed**: this bridge has only run against test doubles of the Boston Dynamics SDK. Nothing here may be reported as verified until a person has run it on a real robot and written the result next to the step.

## What the software already covers (no robot needed)

- `python tools/hydra_project_tool.py test` runs the unit tests: the action table, the validation of coordinates, the intake of a message (a retained one is ignored, a malformed one is refused, a repeated idempotency key is not run twice) and the refusal of a job when the state of the droid was not observed.
- `SpotDroidControl` is tested against a fake command builder and a fake sink, so the commands the bridge would send are checked, not their effect on a body.

## Setup

- A Spot with its physical e-stop within reach, a charged battery and a free area of at least 3 x 3 m, with a person next to the e-stop.
- A computer on the robot network with `bosdyn-client` installed and the bridge installed from this repository.
- The user and password of the robot, kept in the environment of the process and never in a file of the repository.

## Steps

| # | Step | Expected result | Result |
|---|------|-----------------|--------|
| 1 | Open the connection with `open_bosdyn_robot_command` and send nothing else. | The connection opens; no motor starts. | not executed |
| 2 | Send `hold_position` with the robot sitting. | The robot stays still; the answer says it was sent. | not executed |
| 3 | `stand` after a job that was accepted with an observed state of ready. | The robot stands; with no observed state the job is refused and nothing is sent. | not executed |
| 4 | `walk_to` a point 1 m ahead. | The robot walks to the point and stops. | not executed |
| 5 | `walk_to` with a NaN or an infinite coordinate. | Refused before any command is built. | not executed |
| 6 | `ABORT` while walking. | The robot holds position at once; a repeated `ABORT` is forwarded again. | not executed |
| 7 | Send the same job twice with the same idempotency key. | The second one is answered from the store and the robot does not move twice. | not executed |
| 8 | Press the physical e-stop during step 4. | The robot stops by itself; the bridge reports the failure and does not retry the motion. | not executed |
| 9 | `sit`. | The robot stops and sits. | not executed |

| 10 | Run `SpotSession.bring_up()` with `power_on_after_bring_up` false. | The e-stop endpoint registers, the lease is taken, the motors stay off. | not executed |
| 11 | Take the lease from the tablet while the session ticks. | The next tick reports the lease lost, cuts the session and the state reads SAFE_STOP. | not executed |
| 12 | Stop the process during a walk. | The e-stop check-in stops and the robot cuts its motors within `estop_timeout_s`. | not executed |
| 13 | `return_home` and `go_to_waypoint` with a map recorded on the robot. | The robot walks to the waypoint and the status reads reached; an unknown name sends nothing. | not executed |
| 14 | `pick` an object the vision node reports, then `place` inside the reach. | The arm grasps and places it; an object that is not reported is not grasped. | not executed |

## What this bench cannot show

The session, the waypoint navigation and the arm are tested against the emulator and fakes only. How a real robot answers the lease, the e-stop endpoint and the manipulation service is what steps 10 to 14 are for.
