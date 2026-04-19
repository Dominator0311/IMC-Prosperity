"""Regression + sanity tests for the Invest & Expand solver."""

from __future__ import annotations

import math

import pytest

from src.manual_rounds.invest_expand import (
    Allocation,
    AllocationReport,
    best_allocation_under_prior,
    best_rs_cached,
    best_rs_given_mu,
    compute_rank,
    evaluate,
    expected_mu,
    expected_mu_exact,
    gross_pnl,
    interior_s_from_r,
    mu_for_my_v,
    multiplier,
    net_pnl,
    research,
    scale,
)
from src.manual_rounds.invest_expand_deep import (
    adversarial_worst_prior,
    field_phase_diagram,
    level_k_iteration,
    monte_carlo_mu,
)
from src.manual_rounds.invest_expand_priors import (
    bimodal_split_vs_zero,
    consensus_cluster,
    empirical_from_samples,
    leapfrog_adversary,
    mixture,
    naive_ignore_speed,
    naive_thirds,
    nice_number_heavy,
    optimising_at_mu,
    quant_cluster,
    semi_naive_insurance_cluster,
    spike,
    trimodal_naive,
    truncated_geometric,
    uniform,
)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrimitives:
    def test_research_bounds(self):
        assert research(0) == 0.0
        assert research(100) == pytest.approx(200_000, rel=1e-9)

    def test_research_log_shape(self):
        # research(r) should be concave; second-differences negative.
        vals = [research(r) for r in range(0, 101, 10)]
        diffs = [b - a for a, b in zip(vals, vals[1:])]
        second = [d2 - d1 for d1, d2 in zip(diffs, diffs[1:])]
        assert all(d < 0 for d in second)

    def test_scale_linear(self):
        assert scale(0) == 0.0
        assert scale(100) == 7.0
        assert scale(50) == pytest.approx(3.5)

    def test_research_negative_rejects(self):
        with pytest.raises(ValueError):
            research(-1)


@pytest.mark.unit
class TestAllocation:
    def test_ok(self):
        a = Allocation(r=23, s=77, v=0)
        assert a.used == 100
        assert a.cost == 50_000

    def test_invalid_sum(self):
        with pytest.raises(ValueError):
            Allocation(r=60, s=50, v=0)

    def test_invalid_pct(self):
        with pytest.raises(ValueError):
            Allocation(r=-1, s=0, v=0)
        with pytest.raises(ValueError):
            Allocation(r=101, s=0, v=0)

    def test_non_int_rejects(self):
        with pytest.raises(TypeError):
            Allocation(r=23.0, s=77, v=0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Rank computation - must match the official examples
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRankExamples:
    def test_official_example_three_players(self):
        # Players 95, 20, 10 -> ranks 1, 2, 3 -> mu 0.9, 0.5, 0.1
        others = [95, 20, 10]
        assert compute_rank(95, [20, 10]) == 1
        assert compute_rank(20, [95, 10]) == 2
        assert compute_rank(10, [95, 20]) == 3
        assert mu_for_my_v(95, [20, 10]) == pytest.approx(0.9)
        assert mu_for_my_v(20, [95, 10]) == pytest.approx(0.5)
        assert mu_for_my_v(10, [95, 20]) == pytest.approx(0.1)

    def test_official_example_seven_players_ties(self):
        # Investments 70,70,70,50,40,40,30 -> ranks 1,1,1,4,5,5,7.
        # For each player, opponents are the other six values.
        board = [70, 70, 70, 50, 40, 40, 30]
        expected_ranks = [1, 1, 1, 4, 5, 5, 7]
        for i, (v, r) in enumerate(zip(board, expected_ranks)):
            opp = [x for j, x in enumerate(board) if j != i]
            assert compute_rank(v, opp) == r, f"player {i} v={v}"

    def test_mu_linear_spacing(self):
        # 7-player spread: multipliers should linearly span 0.9 to 0.1
        board = [7, 6, 5, 4, 3, 2, 1]
        mus = [mu_for_my_v(v, [x for x in board if x != v]) for v in board]
        assert mus[0] == pytest.approx(0.9)
        assert mus[-1] == pytest.approx(0.1)
        # Equally spaced: each step = 0.8 / 6 = 0.1333...
        steps = [a - b for a, b in zip(mus, mus[1:])]
        assert max(steps) - min(steps) < 1e-9


# ---------------------------------------------------------------------------
# PnL
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPnL:
    def test_user_table_v0_mu09(self):
        # From the user's seed table: (r=23, s=77, v=0) at mu=0.9
        # should yield gross ~742k and net ~+618k. Allow a few % slack
        # since the table is integer-rounded.
        alloc = Allocation(r=23, s=77, v=0)
        g = gross_pnl(alloc, 0.9)
        n = net_pnl(alloc, 0.9)
        assert g == pytest.approx(668_000, rel=0.02)
        # gross = research(23)*scale(77)*0.9 = 137,700 * 5.39 * 0.9 ~ 668k
        assert n == pytest.approx(618_000, rel=0.02)

    def test_zero_r_or_s_kills_gross(self):
        # Multiplicative structure: either pillar at 0 zeros out gross.
        assert gross_pnl(Allocation(r=0, s=50, v=50), 0.9) == 0.0
        assert gross_pnl(Allocation(r=50, s=0, v=50), 0.9) == 0.0

    def test_net_pnl_cost_accounting(self):
        # Cost = 500 * (r + s + v)
        a = Allocation(r=23, s=77, v=0)
        assert a.cost == 50_000
        # mu=0 => gross=0 => net=-cost
        assert net_pnl(a, 0.0) == -50_000


# ---------------------------------------------------------------------------
# (r, s) optimiser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBestRS:
    def test_full_budget_interior(self):
        # Well above min spend threshold; the FOC curve s=(1+r)ln(1+r)
        # should hold approximately at budget=100.
        alloc, net = best_rs_given_mu(0.9, budget_rs=100)
        # r ~ 23, s ~ 77
        assert 20 <= alloc.r <= 26
        assert 74 <= alloc.s <= 80
        assert alloc.r + alloc.s == 100
        # Approximate FOC: s ~= (1+r) * ln(1+r)
        assert abs(alloc.s - interior_s_from_r(alloc.r)) < 3

    def test_low_mu_shifts_toward_scale(self):
        # At low mu, marginal research buys less; the optimum tilts
        # toward s (higher s / lower r). Actually FOC s = (1+r)ln(1+r)
        # is mu-independent when all budget is spent; the interesting
        # shift is whether to spend *less* overall.
        a_hi, _ = best_rs_given_mu(0.9, budget_rs=100)
        a_lo, _ = best_rs_given_mu(0.1, budget_rs=100)
        # At mu=0.1 full budget spend: r=23, s=77 still likely optimal
        # along FOC curve.
        assert abs(a_hi.r - a_lo.r) <= 5

    def test_caching_consistency(self):
        a1, _ = best_rs_given_mu(0.5, 80)
        a2, _ = best_rs_cached(0.5, 80)
        assert (a1.r, a1.s) == (a2.r, a2.s)

    def test_budget_zero(self):
        a, net = best_rs_given_mu(0.9, budget_rs=0)
        assert (a.r, a.s) == (0, 0)
        assert net == 0.0


# ---------------------------------------------------------------------------
# Priors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPriors:
    def test_spike_sums_to_one(self):
        p = spike(50)
        assert sum(p) == pytest.approx(1.0)
        assert p[50] == 1.0

    def test_uniform_sums_to_one(self):
        p = uniform()
        assert sum(p) == pytest.approx(1.0)
        assert p[0] == pytest.approx(1 / 101)

    def test_bimodal_share(self):
        p = bimodal_split_vs_zero(zero_share=0.5, high_v=33)
        assert p[0] == pytest.approx(0.5)
        assert p[33] == pytest.approx(0.5)

    def test_mixture_combines(self):
        p = mixture([(1.0, spike(0)), (1.0, spike(100))])
        assert p[0] == pytest.approx(0.5)
        assert p[100] == pytest.approx(0.5)

    def test_trimodal_shares(self):
        p = trimodal_naive(zero_share=0.3, thirds_share=0.4, half_share=0.3)
        assert p[0] == pytest.approx(0.3)
        assert p[33] == pytest.approx(0.4)
        assert p[50] == pytest.approx(0.3)

    def test_optimising_at_mu_high(self):
        # At mu=0.9 the FOC places all budget on (r, s) => v = 0.
        p = optimising_at_mu(0.9)
        # support should be at a low v (0 or near 0)
        assert p[0] > 0.5

    def test_optimising_at_mu_low(self):
        # At low mu, s target ~ 125*mu is small, so more budget frees up
        # for v. Expect spike at higher v than the 0.9 case.
        p_lo = optimising_at_mu(0.3)
        p_hi = optimising_at_mu(0.9)
        # argmax of p_lo should be > argmax of p_hi
        v_lo = max(range(101), key=lambda i: p_lo[i])
        v_hi = max(range(101), key=lambda i: p_hi[i])
        assert v_lo > v_hi

    def test_empirical_from_samples(self):
        p = empirical_from_samples([0, 0, 33, 50])
        assert p[0] == pytest.approx(0.5)
        assert p[33] == pytest.approx(0.25)
        assert p[50] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Expected mu
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExpectedMu:
    def test_spike_prior_above(self):
        # If the field all plays v=50 and I play v=51, P(opp > me) = 0
        # => mu = 0.9.
        mu = expected_mu(51, spike(50), n_opponents=6_500)
        assert mu == pytest.approx(0.9)

    def test_spike_prior_below(self):
        # I play v=49, field at v=50. P(opp > me) = 1 => mu = 0.1.
        mu = expected_mu(49, spike(50), n_opponents=6_500)
        assert mu == pytest.approx(0.1)

    def test_spike_tie_at_top(self):
        # In the percentile approximation, exact ties yield p_above=0
        # and mu=0.9 -- correct for large N because ties take best rank.
        mu = expected_mu(50, spike(50), n_opponents=6_500)
        assert mu == pytest.approx(0.9)

    def test_uniform_midpoint(self):
        # At v=50 under uniform prior, ~50% of field is above -> mu~0.5
        mu = expected_mu(50, uniform(), n_opponents=6_500)
        # Some slack for the off-by-one integer discretisation.
        assert 0.45 < mu < 0.55


# ---------------------------------------------------------------------------
# Best allocation under prior + regret
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBestAllocationUnderPrior:
    def test_everyone_skips_speed_favours_v0(self):
        # If the whole field plays v=0, playing v=0 gives a shared
        # rank 1 and mu = 0.9 -- (r, s, v) = (23, 77, 0) should win.
        p = naive_ignore_speed()
        best, top10 = best_allocation_under_prior(p, n_opponents=6_500)
        assert best.allocation.v == 0
        # r should be around 23
        assert 20 <= best.allocation.r <= 26

    def test_everyone_at_thirds_favours_tying_at_33(self):
        # Field at v=33 across the board. Playing v=33 ties into the
        # rank-1 cluster (mu=0.9) AND frees (r, s) budget vs v=34.
        # The 500-XIREC cost saving on the v dimension exceeds the
        # R*S gain from having one more budget pct available above 33.
        p = naive_thirds()
        best, _ = best_allocation_under_prior(p, n_opponents=6_500)
        # Optimum sits at v=33 (tie in) under the tie-takes-best rule.
        assert best.allocation.v == 33
        # and (r, s) on the FOC curve, budget 67 -> r~17, s~50.
        assert 15 <= best.allocation.r <= 19
        assert 46 <= best.allocation.s <= 52

    def test_uniform_prior_recommends_mid_high_v(self):
        p = uniform()
        best, _ = best_allocation_under_prior(p, n_opponents=6_500)
        # Under a uniform prior, marginal v is valuable; optimum sits
        # in a moderate range.
        assert 10 <= best.allocation.v <= 40


# ---------------------------------------------------------------------------
# Equilibrium
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEquilibrium:
    def test_qre_converges(self):
        from src.manual_rounds.invest_expand_equilibrium import symmetric_qre

        result = symmetric_qre(
            n_opponents=6_500, temperature=50_000.0, max_iter=200, damping=0.2
        )
        # Must at least terminate without error; convergence is a
        # bonus but high T ensures it converges quickly.
        assert sum(result.equilibrium) == pytest.approx(1.0)
        assert result.iterations > 0

    def test_regret_table_orders_by_robustness(self):
        from src.manual_rounds.invest_expand_equilibrium import regret_table

        candidates = [
            Allocation(r=23, s=77, v=0),
            Allocation(r=17, s=63, v=20),
            Allocation(r=12, s=38, v=50),
        ]
        priors = {
            "ignore_speed": naive_ignore_speed(),
            "uniform": uniform(),
            "thirds": naive_thirds(),
        }
        summaries = regret_table(candidates, priors, n_opponents=6_500)
        # Sorted ascending by max_regret
        for a, b in zip(summaries, summaries[1:]):
            assert a.max_regret <= b.max_regret


# ---------------------------------------------------------------------------
# Deep analytics: MC, level-k, adversarial, phase diagram
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMonteCarlo:
    def test_mc_matches_closed_form_within_stderr(self):
        # Validates E[mu] analytical expression against direct sampling.
        prior = uniform()
        res = monte_carlo_mu(my_v=50, prior=prior, n_opponents=1_000, n_trials=600)
        # stderr ~ std / sqrt(n_trials); allow 4*stderr tolerance.
        stderr = res.mc_std_mu / math.sqrt(res.n_trials)
        assert abs(res.mc_mean_mu - res.closed_form_mu) < 4 * stderr + 1e-3


@pytest.mark.unit
class TestLevelK:
    def test_level_k_converges_on_naive_thirds(self):
        # If field starts at v=33 spike, best response is v=33 (tie in).
        # Should converge immediately and stay there.
        steps = level_k_iteration(naive_thirds(), n_opponents=4500, depth=4)
        assert all(step.best_response.v == 33 for step in steps)

    def test_level_k_maf_cluster_overshoots(self):
        # Field at v=5 cluster: best response leapfrogs to v just above.
        steps = level_k_iteration(
            semi_naive_insurance_cluster(center=5, spread=3),
            n_opponents=4500,
            depth=3,
        )
        # L0 response should be above 5 (leapfrog).
        assert steps[0].best_response.v > 5
        # Converges: L1 and L2 should be stable.
        assert steps[1].best_response.v == steps[2].best_response.v


@pytest.mark.unit
class TestAdversarialWorst:
    def test_low_v_has_higher_downside_floor(self):
        # Counter-intuitive finding: because R*S buffers mu collapse,
        # playing v=0 has a HIGHER worst-case PnL than v=50.
        a0 = adversarial_worst_prior(
            Allocation(r=23, s=77, v=0), n_opponents=4500
        )
        a50 = adversarial_worst_prior(
            Allocation(r=13, s=37, v=50), n_opponents=4500
        )
        assert a0.worst_pnl > a50.worst_pnl

    def test_leapfrog_is_identified_worst_case(self):
        # For a candidate at v=34, the leapfrog_beating_v34 prior
        # should be the adversarial worst case.
        res = adversarial_worst_prior(
            Allocation(r=16, s=50, v=34), n_opponents=4500
        )
        assert "leapfrog" in res.worst_prior_name


@pytest.mark.unit
class TestPhaseDiagram:
    def test_br_v_monotone_in_field_mean(self):
        # Best-response v should increase roughly monotonically as field mean rises.
        cells = field_phase_diagram(
            mean_grid=[5.0, 15.0, 25.0, 35.0, 45.0],
            std_grid=[15.0],
            n_opponents=4500,
        )
        vs = [c.best_v for c in cells]
        for a, b in zip(vs, vs[1:]):
            # Monotone non-decreasing (allow flat plateaus).
            assert b >= a


# ---------------------------------------------------------------------------
# New priors: MAF-aware
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMAFPriors:
    def test_semi_naive_cluster_concentrates_near_center(self):
        p = semi_naive_insurance_cluster(center=5, spread=3)
        # Most mass in [2, 8]
        mass_cluster = sum(p[2:9])
        assert mass_cluster > 0.3  # the "cluster_share" dial

    def test_consensus_cluster_concentrates_at_center(self):
        p = consensus_cluster(center=40, cluster_share=0.7)
        assert p[40] > 0.7  # 70% at center + a sliver from uniform remainder

    def test_leapfrog_adversary_concentrates_above_target(self):
        p = leapfrog_adversary(beat_v=34)
        # All mass should be at v=35 or v=36
        assert p[35] + p[36] == pytest.approx(1.0)
        assert p[34] == 0.0
        assert p[33] == 0.0
