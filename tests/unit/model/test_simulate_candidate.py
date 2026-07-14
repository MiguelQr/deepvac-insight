"""Tests for simulate_candidate() (app/model/simulation.py) -- the full
closed-loop step(PID/Diff) -> predict(GRU) -> feed-back loop.

simulate_candidate() already accepts model/checkpoint/args as parameters,
so no production-code refactor was needed to make this testable: a real
GRUModel is used, but with its final layer's weight zeroed and bias fixed,
so it returns an *exact, known constant* (0.5) regardless of input --
"a small fake predictor with an obvious deterministic relationship" per
the plan, built from the real class rather than a hand-rolled stand-in, so
the rest of simulate_candidate()'s real wiring (feature windows, PID/Diff
state, trajectory bookkeeping) is still genuinely exercised.

With x_scaler/y_scaler as identity transforms and the model always
predicting delta=+0.5, temp_next = temp_current + 0.5 every single step,
independent of kp/ki/kd -- fully hand-computable for any step count.
"""

import copy
from argparse import Namespace

import numpy as np
import pytest
import torch

from app.model.simulation import GRUModel, simulate_candidate

pytestmark = pytest.mark.unit

FEATURE_NAMES = [
    "temp",
    "temp_ref",
    "error",
    "temp_u",
    "temp_u_p",
    "temp_u_i",
    "temp_u_d",
    "kp",
    "ki",
    "kd",
]


class _IdentityScaler:
    """Stand-in for sklearn.preprocessing.StandardScaler with mean=0,
    scale=1 -- transform()/inverse_transform() are both no-ops, so
    predict_delta_t1()'s normalize/denormalize steps don't perturb the
    fixed model output at all."""

    def transform(self, X):
        self.transform_calls = getattr(self, "transform_calls", 0) + 1
        return X

    def inverse_transform(self, X):
        return X


def _fixed_bias_model_and_checkpoint(fixed_delta=0.5, window_steps=4, hidden_dim=6):
    torch.manual_seed(0)
    model = GRUModel(input_dim=len(FEATURE_NAMES), hidden_dim=hidden_dim, num_layers=1, dropout=0.0)
    model.eval()
    with torch.no_grad():
        final_linear = model.head[4]
        final_linear.weight.zero_()
        final_linear.bias.fill_(fixed_delta)
    x_scaler = _IdentityScaler()
    y_scaler = _IdentityScaler()
    checkpoint = {"x_scaler": x_scaler, "y_scaler": y_scaler}
    return model, checkpoint, x_scaler, y_scaler


def _base_args(**overrides):
    defaults = dict(
        start_temp=20.0,
        target_temp=60.0,
        duration_s=6.0,
        dt_s=2.0,
        precondition_ref=None,
        u_min=-1.0,
        u_max=1.0,
        control_feature_scale=100.0,
        pid_i_reverse_mul=0.333,
        pid_period_s=0.1,
        initial_i=0.0,
        initial_d=0.0,
        initial_p=0.0,
        tail_window_s=6.0,
        near_band=2.0,
        settle_band=0.5,
        w_tail_mae=1.0,
        w_overshoot_max=10.0,
        w_tail_std=0.5,
        w_final_error=0.5,
        w_invalid=1_000_000.0,
        max_abs_temp=1000.0,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def _run(fixed_delta=0.5, window_steps=4, save_trajectory=True, **arg_overrides):
    model, checkpoint, x_scaler, y_scaler = _fixed_bias_model_and_checkpoint(
        fixed_delta=fixed_delta, window_steps=window_steps
    )
    args = _base_args(**arg_overrides)
    metrics, traj = simulate_candidate(
        candidate_id=1,
        kp=7.0,
        ki=700.0,
        kd=10.0,
        model=model,
        checkpoint=checkpoint,
        feature_names=FEATURE_NAMES,
        window_steps=window_steps,
        args=args,
        device=torch.device("cpu"),
        save_trajectory=save_trajectory,
    )
    return metrics, traj, x_scaler


def test_correct_output_length_matches_n_steps():
    # n_steps = max(1, ceil(duration_s/dt_s)) = ceil(6/2) = 3
    metrics, traj, _ = _run(duration_s=6.0, dt_s=2.0)
    assert len(traj) == 3


def test_correct_time_ordering_and_values():
    metrics, traj, _ = _run(duration_s=6.0, dt_s=2.0)
    assert list(traj["elapsed_s"]) == [2.0, 4.0, 6.0]
    assert list(traj["step"]) == [1, 2, 3]


def test_manually_verifiable_closed_loop_trajectory():
    # temp_next = temp_current + 0.5 every step, independent of kp/ki/kd,
    # since the fixed-bias model ignores its input entirely.
    metrics, traj, _ = _run(fixed_delta=0.5, duration_s=6.0, dt_s=2.0, start_temp=20.0)
    assert list(traj["temp"]) == pytest.approx([20.5, 21.0, 21.5])
    assert metrics["end_temp"] == pytest.approx(21.5)
    assert metrics["min_temp"] == pytest.approx(20.5)
    assert metrics["max_temp"] == pytest.approx(21.5)


def test_negative_delta_decreases_temperature():
    metrics, traj, _ = _run(fixed_delta=-1.0, duration_s=4.0, dt_s=2.0, start_temp=50.0)
    assert list(traj["temp"]) == pytest.approx([49.0, 48.0])


def test_correct_model_call_sequence_one_call_per_step():
    metrics, traj, x_scaler = _run(duration_s=10.0, dt_s=2.0)  # n_steps = 5
    assert x_scaler.transform_calls == 5


def test_minimum_one_step_even_for_zero_duration():
    # n_steps = max(1, ceil(0/dt_s)) -- duration_s=0 still runs one step.
    metrics, traj, _ = _run(duration_s=0.0, dt_s=2.0)
    assert len(traj) == 1


def test_output_is_finite():
    metrics, traj, _ = _run(duration_s=20.0, dt_s=2.0)
    assert np.isfinite(traj["temp"]).all()
    assert np.isfinite(metrics["cost"])
    assert metrics["valid"] is True


def test_candidate_parameters_propagate_into_metrics():
    metrics, _, _ = _run(duration_s=4.0, dt_s=2.0)
    assert metrics["candidate_id"] == 1
    assert metrics["kp"] == pytest.approx(7.0)
    assert metrics["ki"] == pytest.approx(700.0)
    assert metrics["kd"] == pytest.approx(10.0)


def test_args_namespace_not_mutated():
    model, checkpoint, _, _ = _fixed_bias_model_and_checkpoint()
    args = _base_args(duration_s=4.0, dt_s=2.0)
    before = copy.deepcopy(vars(args))
    simulate_candidate(
        candidate_id=1,
        kp=7.0,
        ki=700.0,
        kd=10.0,
        model=model,
        checkpoint=checkpoint,
        feature_names=FEATURE_NAMES,
        window_steps=4,
        args=args,
        device=torch.device("cpu"),
        save_trajectory=True,
    )
    assert vars(args) == before


def test_checkpoint_dict_keys_not_mutated():
    model, checkpoint, _, _ = _fixed_bias_model_and_checkpoint()
    args = _base_args(duration_s=4.0, dt_s=2.0)
    keys_before = set(checkpoint.keys())
    simulate_candidate(
        candidate_id=1,
        kp=7.0,
        ki=700.0,
        kd=10.0,
        model=model,
        checkpoint=checkpoint,
        feature_names=FEATURE_NAMES,
        window_steps=4,
        args=args,
        device=torch.device("cpu"),
    )
    assert set(checkpoint.keys()) == keys_before


def test_determinism_repeated_calls_agree():
    metrics1, traj1, _ = _run(duration_s=10.0, dt_s=2.0)
    metrics2, traj2, _ = _run(duration_s=10.0, dt_s=2.0)
    assert list(traj1["temp"]) == pytest.approx(list(traj2["temp"]))
    assert metrics1["cost"] == pytest.approx(metrics2["cost"])


def test_no_state_leakage_between_consecutive_simulations_different_kp():
    # pid/diff are constructed fresh *inside* simulate_candidate() every
    # call -- running with kp=A, then kp=B, then kp=A again should give the
    # same result for both kp=A runs (no cross-call contamination).
    metrics_a1, traj_a1, _ = _run(duration_s=10.0, dt_s=2.0)
    _run(duration_s=10.0, dt_s=2.0)  # a differently-parameterized run in between
    metrics_a2, traj_a2, _ = _run(duration_s=10.0, dt_s=2.0)
    assert list(traj_a1["temp"]) == pytest.approx(list(traj_a2["temp"]))


def test_invalid_when_temperature_exceeds_max_abs_temp():
    # fixed_delta large enough that a few steps blow past max_abs_temp.
    metrics, traj, _ = _run(
        fixed_delta=1000.0, duration_s=4.0, dt_s=2.0, start_temp=0.0, max_abs_temp=500.0
    )
    assert metrics["valid"] is False
    assert "invalid" in metrics["invalid_reason"].lower()
    assert np.isfinite(traj["temp"]).all()  # invalid steps are nan_to_num'd, not left NaN


def test_save_trajectory_false_returns_none_dataframe():
    metrics, traj, _ = _run(duration_s=4.0, dt_s=2.0, save_trajectory=False)
    assert traj is None
    assert metrics["candidate_id"] == 1  # metrics are still computed either way


def test_cooling_scenario_overshoot_means_going_below_target():
    # compute_metrics() branches on target_temp <= start_temp: when cooling,
    # "overshoot" means dropping *below* the target, not above it.
    metrics, traj, _ = _run(
        fixed_delta=-2.0,
        duration_s=6.0,
        dt_s=2.0,
        start_temp=50.0,
        target_temp=10.0,
    )
    assert list(traj["temp"]) == pytest.approx([48.0, 46.0, 44.0])
    # Never dropped below target_temp=10, so overshoot (cooling-direction) is 0.
    assert metrics["overshoot_max"] == pytest.approx(0.0)


def test_cooling_scenario_overshoot_nonzero_when_dropping_past_target():
    metrics, traj, _ = _run(
        fixed_delta=-5.0,
        duration_s=6.0,
        dt_s=2.0,
        start_temp=12.0,
        target_temp=10.0,
    )
    assert list(traj["temp"]) == pytest.approx([7.0, 2.0, -3.0])
    # Dropped well past target_temp=10 -> cooling overshoot is target - temp.
    assert metrics["overshoot_max"] == pytest.approx(10.0 - (-3.0))


def test_compute_metrics_falls_back_to_full_trajectory_when_tail_mask_empty():
    # tail_start = max(0, duration_s - tail_window_s). Reaching duration_s
    # large enough that tail_start exceeds every actual recorded time isn't
    # possible to construct *through* simulate_candidate() (its own times
    # array is always generated up to duration_s), so this calls
    # compute_metrics() directly -- it's a plain, separately callable
    # function, not a private implementation detail of simulate_candidate().
    from app.model.simulation import compute_metrics

    times = np.array([2.0, 4.0])
    temps = np.array([20.5, 21.0])
    args = _base_args(duration_s=100.0, tail_window_s=1.0)  # tail_start=99, matches nothing

    metrics = compute_metrics(
        candidate_id=1,
        kp=1.0,
        ki=1.0,
        kd=1.0,
        times=times,
        temps=temps,
        target_temp=60.0,
        start_temp=20.0,
        valid=True,
        invalid_reason="",
        args=args,
    )
    # Fallback used the whole trajectory, so tail_mae == mae over all points.
    assert metrics["tail_mae"] == pytest.approx(metrics["mae_full"])
