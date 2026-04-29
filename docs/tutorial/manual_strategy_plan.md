# IMC Prosperity Manual Round Strategy & Execution Plan

## Purpose

Build a dedicated manual-round workflow so the team can respond quickly and intelligently to IMC Prosperity manual challenges.

The goal is not to solve past rounds mechanically.
The goal is to create a **repeatable decision system** for future manual rounds using:
- solver templates
- optimization templates
- game-theory reasoning
- psychological-bias priors where relevant
- clean validation and submission workflow

This is a separate workstream from the algorithmic bot and should be treated as one.

---

# 1. Why a separate manual-round plan is necessary

Manual rounds matter.
They can materially affect total competition outcome.

They often reward:
- fast modeling
- clear optimization thinking
- understanding incentives
- recognizing repeated structure from prior years
- using priors intelligently
- avoiding overcomplicated but fragile modeling

The winning-analysis transcript strongly suggests that many manual rounds reduce to a few reusable problem families.

---

# 2. Core philosophy

## 2.1 Solve structurally, not ad hoc
We want reusable templates for the most common manual-round classes.

## 2.2 Start from the simplest valid model
Use the simplest model that captures the incentives.
Only add realism if it changes the decision.

## 2.3 Use priors, but do not worship them
Past years can be highly informative.
But all priors should be stress-tested.

## 2.4 Psychological effects matter only when structure supports them
Examples:
- “nice numbers”
- corner choices
- clustering around salient values

These are useful as overlays, not as the whole model.

## 2.5 Manual-round work must be parallelized
During a live competition, manual-round analysis should run alongside algo-round work, not after it.

---

# 3. Problem taxonomy for manual rounds

These are the main families to prepare for.

## 3.1 Graph / path optimization
Examples:
- currency conversion cycles
- shortest / highest-value path
- multi-step route maximization

Typical tools:
- graph search
- dynamic programming
- brute force over small state spaces

## 3.2 Game-theory / crowd-distribution problems
Examples:
- container / suitcase / selection games
- pick one or more choices while others also choose
- payoff depends on crowding or average behavior

Typical tools:
- Nash-style reasoning
- prior distributions over player behavior
- simulation
- sensitivity analysis

## 3.3 Portfolio / allocation optimization
Examples:
- allocate fractions across assets under nonlinear cost / penalty
- expected return with transaction or allocation penalties

Typical tools:
- constrained optimization
- simulation over priors
- expected value modeling

## 3.4 Market / auction / bid optimization
Examples:
- choose optimal bids under payoff asymmetry
- maximize expected value with strategic penalties

Typical tools:
- expected value formula derivation
- derivative/root solving
- brute-force search over ranges

## 3.5 Sentiment / information interpretation
Examples:
- news items affecting asset returns
- text clues affecting expected outcomes

Typical tools:
- structured interpretation
- prior mapping from sentiment to expected move
- scenario testing

## 3.6 Hybrid rounds
Some rounds combine two or more of the above.
The system must support composition.

---

# 4. Manual-round deliverables

We need a reusable manual-round toolkit with these outputs.

## 4.1 Solver notebook templates
Templates for:
- graph search
- expected value search
- bid optimization
- portfolio allocation
- crowd simulation

## 4.2 Manual-round utilities library
Small Python library with:
- brute force helpers
- simulation helpers
- root solving wrappers
- allocation helpers
- sensitivity analysis helpers

## 4.3 Prior modeling framework
A clean way to encode assumptions about:
- player behavior
- crowd clustering
- “nice number” effects
- rational vs naive populations

## 4.4 Submission review checklist
A compact process so manual answers are not submitted blindly.

---

# 5. Project structure

```text
manual_rounds/
  README.md

  notebooks/
    01_graph_template.ipynb
    02_game_theory_template.ipynb
    03_portfolio_template.ipynb
    04_bid_optimization_template.ipynb
    05_sentiment_template.ipynb
    06_sensitivity_analysis.ipynb

  src/
    utils/
      graph_tools.py
      simulation_tools.py
      optimization_tools.py
      prior_models.py
      sentiment_tools.py
      validation.py

    scripts/
      run_graph_solver.py
      run_simulation.py
      run_portfolio_optimizer.py
      run_bid_optimizer.py
      generate_submission_note.py

  outputs/
    charts/
    simulations/
    notes/
```

---

# 6. Reusable workflow for any manual round

## Step 1 — Identify the round family
Classify the problem first.

Ask:
- Is this a graph problem?
- A game-theory / crowding problem?
- An allocation problem?
- A bid optimization problem?
- A sentiment problem?
- A hybrid?

Do not start coding before classification.

## Step 2 — Write down the payoff function explicitly
Translate the round into math or algorithmic terms.

Document:
- decision variables
- constraints
- payoff / loss function
- what depends on us
- what depends on others

## Step 3 — Solve the simplest no-opponent / naive version first
This gives a clean baseline.

Examples:
- optimal bid if no strategic penalty
- optimal allocation if no crowd effect
- optimal path with deterministic payoffs

This prevents confusion.

## Step 4 — Add the opponent / crowd model
Only now add:
- player priors
- average choice assumptions
- clustering effects
- psychological overlays

## Step 5 — Simulate
Run Monte Carlo or repeated deterministic simulation across priors.

Outputs should include:
- expected value by choice
- sensitivity to prior assumptions
- which decisions are robust vs fragile

## Step 6 — Perform sensitivity analysis
Stress-test:
- prior weights
- crowd fractions
- penalty sizes
- sentiment-to-return mapping

Do not trust one fragile optimum.

## Step 7 — Choose robust answer
Prefer answers that remain good across a range of assumptions.

## Step 8 — Write a submission note
Before submission, record:
- chosen answer
- why it was chosen
- key assumptions
- biggest risk if assumptions are wrong

---

# 7. Templates by problem family

## 7.1 Graph / path template

### Use when
- multiple conversion routes or paths exist
- need highest-value path under limited steps

### Process
1. represent states as graph nodes
2. represent transitions as weighted edges
3. search all feasible paths if state space is small
4. otherwise use DP / graph algorithms
5. validate with brute force on reduced examples

### Outputs
- best path
- top N paths
- sensitivity if edge weights vary

---

## 7.2 Game-theory / crowding template

### Use when
- payoff depends on what others choose
- one or more containers/suitcases/options must be picked

### Process
1. compute naive EV under fully random or fully Nash assumptions
2. build prior distribution over player behavior
3. include optional psychological clusters
4. simulate many runs
5. compare robust options, not just single highest point estimate

### Important rule
If the problem is one-shot, do not overcomplicate equilibrium theory beyond what changes the answer.

### Outputs
- EV ranking under priors
- sensitivity chart
- recommendation and robustness note

---

## 7.3 Portfolio / allocation template

### Use when
- allocate percentages across multiple assets/outcomes
- nonlinear cost or penalty exists

### Process
1. estimate expected moves / returns
2. encode cost function
3. solve constrained optimization
4. test sensitivity to expected-return assumptions
5. compare concentrated vs diversified solutions

### Outputs
- recommended allocation
- allocation under alternative scenarios
- note on which expected-return estimates matter most

---

## 7.4 Bid optimization template

### Use when
- need to choose one or more bid values
- payoffs depend on reserve price and possibly others’ bids

### Process
1. derive EV as function of bid(s)
2. solve analytically if possible
3. otherwise grid search or brute force
4. if crowd penalty exists, add average-bid model
5. test sensitivity to crowd assumptions

### Outputs
- optimal bid(s) under naive model
- adjusted bid(s) under strategic model
- robustness to average-bid shifts

---

## 7.5 Sentiment / information template

### Use when
- text / news / hints affect expected outcomes

### Process
1. convert narrative clues into structured directional hypotheses
2. estimate magnitude using priors or past analogues
3. feed into portfolio / bid / choice optimizer as needed
4. stress-test with softer and stronger assumptions

### Outputs
- expected move table
- confidence / uncertainty note
- downstream optimal decision

---

# 8. Prior modeling framework

Manual rounds often hinge on what other players will do.
We therefore need an explicit prior framework.

## 8.1 Candidate behavioral groups
Examples:
- Nash-like players
- random players
- naive EV players
- psychologically clustered players
- overconfident exploiters
- griefers / weird actors if structure permits

## 8.2 Prior requirements
Priors must be:
- explicit
- editable
- documented
- stress-tested

## 8.3 Nice-number / salience overlay
Include optional weights for:
- 37 / 73-style choices
- corners
- highest visible multiplier
- aesthetically salient values

Use this as an overlay, not the whole model.

---

# 9. Validation protocol

Every manual-round answer must pass this review.

## 9.1 Structural review
- Did we classify the problem correctly?
- Is the payoff function correct?
- Are constraints correctly encoded?

## 9.2 Baseline review
- What is the naive optimal answer without opponents?
- What changes once crowd effects are included?

## 9.3 Robustness review
- Does the answer survive moderate prior shifts?
- Are there close alternatives?
- Is the chosen answer fragile?

## 9.4 Submission note
Before submitting, generate a short note containing:
- final answer
- core assumptions
- backup answer if assumptions fail

---

# 10. AI agent operating rules for manual rounds

## Agents may
- classify round type
- derive formulas
- write simulators
- build notebook workflows
- suggest priors
- generate sensitivity charts

## Agents may not be trusted blindly on
- interpretation of incentives
- payoff formulas without human cross-check
- one-shot answers without robustness analysis

## Acceptance gate
Every manual-round recommendation must include:
1. problem-family classification
2. payoff structure explanation
3. simulation / solver result
4. sensitivity analysis
5. plain-English justification

---

# 11. Implementation phases

## Phase M1 — Toolkit setup
Build project skeleton and utility library.

## Phase M2 — Template notebooks
Create the five main notebook templates.

## Phase M3 — Prior modeling utilities
Implement editable crowd / psychological priors.

## Phase M4 — Validation scripts
Build quick-check scripts and submission-note generator.

## Phase M5 — Practice on prior-year style problems
Use past public examples or analogous synthetic problems to test the workflow.

## Phase M6 — Live-use protocol
Document how manual-round work runs in parallel during the competition.

---

# 12. Recommended live competition workflow for manual rounds

When a manual round opens:

1. classify the problem in under 10 minutes
2. assign it to the correct notebook template
3. derive payoff and baseline solver
4. add priors / crowd model if needed
5. run simulations and sensitivity analysis
6. choose robust answer
7. produce submission note
8. sanity check once before submitting

The main point is to move quickly without becoming sloppy.

---

# 13. Roles for AI-agent collaboration

## Agent 1 — structural modeler
Derives the payoff function and formal model.

## Agent 2 — solver engineer
Builds optimization / simulation code.

## Agent 3 — robustness analyst
Runs sensitivity analysis and alternative priors.

## Agent 4 — summarizer
Produces final submission note and rationale.

This gives you a mini research desk rather than a single-shot assistant.

---

# 14. What good output looks like

A strong manual-round output should include:
- the chosen answer
- a ranked list of alternatives
- the baseline no-opponent solution
- the crowd-adjusted solution
- the main assumptions
- the answer’s robustness range

If the output does not include that, it is not ready.

---

# 15. Success criteria

This manual-round plan is successful if it gives you:
- fast classification of new manual problems
- reusable solver templates
- explicit priors rather than vague intuition
- robustness checks before submission
- a parallel workstream that improves total competition outcome

The point is not to memorize old solutions.
The point is to build a **repeatable manual-round decision engine**.
