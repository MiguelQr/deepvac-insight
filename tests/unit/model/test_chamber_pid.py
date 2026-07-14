"""Characterization tests for ChamberPID (app/model/simulation.py), the
Python port of gru/codesys/pid.txt (Chamber_Control PID block).

Every expected value below is hand-derived directly from the documented
step() formula (see app/model/simulation.py's ChamberPID.step docstring/
body) as a plain arithmetic expression written independently in each test
-- never by importing or re-executing the implementation being tested.
"""

import pytest

from app.model.simulation import ChamberPID

pytestmark = pytest.mark.unit


def test_initial_state_is_zero():
    pid = ChamberPID()
    assert pid.p_part == 0.0
    assert pid.i_part == 0.0
    assert pid.d_part == 0.0


def test_disabled_zeroes_and_returns_all_zero():
    pid = ChamberPID(u_min=-1.0, u_max=1.0)
    pid.p_part, pid.i_part, pid.d_part = 5.0, 5.0, 5.0
    u, p, i, d = pid.step(
        enable=False, x_target=100, x_measured=0, p_coef=1.0, i_coef=1.0, d_coef=1.0, diff_out=0.0
    )
    assert (u, p, i, d) == (0.0, 0.0, 0.0, 0.0)
    assert (pid.p_part, pid.i_part, pid.d_part) == (0.0, 0.0, 0.0)


def test_zero_p_coef_returns_early_without_changing_state():
    # step() explicitly guards `if p_coef == 0.0: return 0.0, <unchanged>`
    pid = ChamberPID()
    pid.p_part, pid.i_part, pid.d_part = 0.3, 0.2, 0.1
    u, p, i, d = pid.step(
        enable=True, x_target=10, x_measured=0, p_coef=0.0, i_coef=1.0, d_coef=1.0, diff_out=0.5
    )
    assert u == 0.0
    assert (p, i, d) == (0.3, 0.2, 0.1)


def test_proportional_only_response():
    # i_coef=0 and d_coef=0 isolate the P term entirely.
    pid = ChamberPID(u_min=-1.0, u_max=1.0, pid_i_reverse_mul=0.333)
    p_coef, delta = 2.0, 2.0  # x_target=10, x_measured=8
    u, p, i, d = pid.step(
        enable=True,
        x_target=10.0,
        x_measured=8.0,
        p_coef=p_coef,
        i_coef=0.0,
        d_coef=0.0,
        diff_out=0.0,
    )
    expected_p = (1.0 / p_coef) * delta  # = 1.0
    assert u == pytest.approx(expected_p)
    assert p == pytest.approx(expected_p)
    assert i == 0.0
    assert d == 0.0


def test_zero_error_leaves_i_part_unchanged_and_p_d_zero():
    pid = ChamberPID()
    u, p, i, d = pid.step(
        enable=True,
        x_target=5.0,
        x_measured=5.0,
        p_coef=2.0,
        i_coef=1.0,
        d_coef=0.0,
        diff_out=0.0,
    )
    assert (u, p, i, d) == (0.0, 0.0, 0.0, 0.0)


def test_derivative_response_to_known_diff_out():
    # delta=0 isolates D; only diff_out and d_coef drive the output.
    pid = ChamberPID(u_min=-1.0, u_max=1.0)
    p_coef, d_coef, diff_out = 2.0, 1.0, 0.4
    u, p, i, d = pid.step(
        enable=True,
        x_target=5.0,
        x_measured=5.0,
        p_coef=p_coef,
        i_coef=0.0,
        d_coef=d_coef,
        diff_out=diff_out,
    )
    expected_d = (1.0 / p_coef) * (d_coef * -diff_out)  # = 0.5 * (1.0 * -0.4) = -0.2
    assert d == pytest.approx(expected_d)
    assert u == pytest.approx(expected_d)
    assert p == 0.0


def test_integral_accumulates_over_multiple_steps_same_sign_delta():
    pid = ChamberPID(u_min=-1.0, u_max=1.0, pid_i_reverse_mul=0.333)
    p_coef, i_coef = 2.0, 1.0
    delta = 1.0  # x_target=10, x_measured=9, held constant across both steps

    u1, p1, i1, d1 = pid.step(
        enable=True,
        x_target=10.0,
        x_measured=9.0,
        p_coef=p_coef,
        i_coef=i_coef,
        d_coef=0.0,
        diff_out=0.0,
    )
    # First call: prior i_part=0, so delta*i_part=0 (not <0) -> effective_i_coef stays i_coef.
    expected_i1 = 0.0 + (1.0 / p_coef) * (delta * 0.1 / i_coef)  # = 0.05
    expected_p = (1.0 / p_coef) * delta  # = 0.5, same both steps
    assert p1 == pytest.approx(expected_p)
    assert i1 == pytest.approx(expected_i1)
    assert u1 == pytest.approx(expected_p + expected_i1)

    u2, p2, i2, d2 = pid.step(
        enable=True,
        x_target=10.0,
        x_measured=9.0,
        p_coef=p_coef,
        i_coef=i_coef,
        d_coef=0.0,
        diff_out=0.0,
    )
    # Second call: prior i_part=expected_i1 (positive), delta still positive ->
    # delta*i_part > 0, not <0 -> effective_i_coef stays i_coef again.
    expected_i2 = expected_i1 + (1.0 / p_coef) * (delta * 0.1 / i_coef)  # = 0.10
    assert i2 == pytest.approx(expected_i2)
    assert p2 == pytest.approx(expected_p)
    assert u2 == pytest.approx(expected_p + expected_i2)
    assert i2 > i1  # accumulated further in the same direction


def test_integral_reverse_gain_when_delta_opposes_accumulated_i_part():
    # Build up a positive i_part, then flip delta's sign: step() should
    # multiply i_coef by pid_i_reverse_mul on this step (the "unwind faster"
    # branch), not apply the full i_coef.
    pid = ChamberPID(u_min=-1.0, u_max=1.0, pid_i_reverse_mul=0.333)
    p_coef, i_coef = 2.0, 1.0
    pid.step(  # accumulate: i_part -> 0.05
        enable=True,
        x_target=10.0,
        x_measured=9.0,
        p_coef=p_coef,
        i_coef=i_coef,
        d_coef=0.0,
        diff_out=0.0,
    )
    prior_i_part = pid.i_part
    assert prior_i_part == pytest.approx(0.05)

    u, p, i, d = pid.step(  # now delta flips negative while i_part is still positive
        enable=True,
        x_target=9.0,
        x_measured=10.0,
        p_coef=p_coef,
        i_coef=i_coef,
        d_coef=0.0,
        diff_out=0.0,
    )
    delta = -1.0
    effective_i_coef = i_coef * 0.333  # delta * prior_i_part < 0 -> reverse branch
    expected_p = (1.0 / p_coef) * delta  # = -0.5
    expected_i = prior_i_part + (1.0 / p_coef) * (delta * 0.1 / effective_i_coef)
    assert p == pytest.approx(expected_p)
    assert i == pytest.approx(expected_i)
    assert i < prior_i_part  # unwinding back down, not still climbing


def test_i_part_anti_windup_clips_to_u_min_u_max():
    # Tight bounds + repeated same-direction accumulation should saturate
    # i_part at u_max and hold it there, not grow past it.
    pid = ChamberPID(u_min=-0.05, u_max=0.05, pid_i_reverse_mul=0.333)
    p_coef, i_coef = 2.0, 1.0
    for _ in range(5):
        _, _, i, _ = pid.step(
            enable=True,
            x_target=10.0,
            x_measured=9.0,
            p_coef=p_coef,
            i_coef=i_coef,
            d_coef=0.0,
            diff_out=0.0,
        )
        assert -0.05 <= i <= 0.05
    assert pid.i_part == pytest.approx(0.05)  # saturated at u_max


def test_d_part_clips_to_fixed_point_four_band_regardless_of_u_bounds():
    # d_part's clamp (-0.4, 0.4) is a fixed constant in step(), independent
    # of the instance's own u_min/u_max. (1/1)*(1000*-1.0) = -1000 -> -0.4.
    pid = ChamberPID(u_min=-100.0, u_max=100.0)
    _, _, _, d = pid.step(
        enable=True,
        x_target=5.0,
        x_measured=5.0,
        p_coef=1.0,
        i_coef=0.0,
        d_coef=1000.0,
        diff_out=1.0,
    )
    assert d == -0.4


def test_d_part_clips_negative_direction_too():
    # (1/1)*(1000*-(-1.0)) = 1000 -> clipped to +0.4.
    pid = ChamberPID(u_min=-100.0, u_max=100.0)
    _, _, _, d = pid.step(
        enable=True,
        x_target=5.0,
        x_measured=5.0,
        p_coef=1.0,
        i_coef=0.0,
        d_coef=1000.0,
        diff_out=-1.0,
    )
    assert d == 0.4


def test_u_output_clips_to_instance_u_min_u_max():
    pid = ChamberPID(u_min=-0.1, u_max=0.1)
    u, p, i, d = pid.step(
        enable=True,
        x_target=100.0,
        x_measured=0.0,
        p_coef=1.0,
        i_coef=0.0,
        d_coef=0.0,
        diff_out=0.0,
    )
    assert u == 0.1  # raw p_part would be 100, clipped
    assert p == 0.1  # logged p_part is clipped the same way


def test_positive_and_negative_errors_are_antisymmetric_for_p_only():
    pid_pos = ChamberPID(u_min=-10.0, u_max=10.0)
    pid_neg = ChamberPID(u_min=-10.0, u_max=10.0)
    u_pos, p_pos, _, _ = pid_pos.step(
        enable=True,
        x_target=10.0,
        x_measured=8.0,
        p_coef=2.0,
        i_coef=0.0,
        d_coef=0.0,
        diff_out=0.0,
    )
    u_neg, p_neg, _, _ = pid_neg.step(
        enable=True,
        x_target=8.0,
        x_measured=10.0,
        p_coef=2.0,
        i_coef=0.0,
        d_coef=0.0,
        diff_out=0.0,
    )
    assert u_pos == pytest.approx(-u_neg)
    assert p_pos == pytest.approx(-p_neg)


def test_reset_is_reconstruction_or_explicit_field_assignment():
    # ChamberPID has no reset() method -- simulate_candidate() "resets" by
    # either constructing a fresh instance or assigning p_part/i_part/d_part
    # directly (see its own use of args.initial_p/i/d). Both are
    # characterized here since that's the only reset mechanism that exists.
    pid = ChamberPID()
    # delta=1.0, delta_edge=1.2*p_coef=1.2 -> abs(delta) < delta_edge, so the
    # integral term actually updates this step (a delta of 10 wouldn't:
    # it'd be outside the update band and i_part would stay 0).
    pid.step(
        enable=True,
        x_target=1.0,
        x_measured=0.0,
        p_coef=1.0,
        i_coef=1.0,
        d_coef=1.0,
        diff_out=1.0,
    )
    assert pid.i_part != 0.0

    fresh = ChamberPID()
    assert (fresh.p_part, fresh.i_part, fresh.d_part) == (0.0, 0.0, 0.0)

    pid.p_part = pid.i_part = pid.d_part = 0.0
    assert (pid.p_part, pid.i_part, pid.d_part) == (0.0, 0.0, 0.0)


def test_repeated_execution_is_deterministic():
    def run():
        pid = ChamberPID(u_min=-1.0, u_max=1.0, pid_i_reverse_mul=0.333)
        results = []
        for x_measured in (9.0, 9.5, 8.7, 9.9, 9.0):
            results.append(
                pid.step(
                    enable=True,
                    x_target=10.0,
                    x_measured=x_measured,
                    p_coef=2.0,
                    i_coef=1.0,
                    d_coef=0.5,
                    diff_out=0.1,
                )
            )
        return results

    assert run() == run()
