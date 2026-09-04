---
title: Cognitive Architectures, Selective Attention, and Decision Making
kind: topic_source
category: psychology
scope: survey
source: "Daniel Kahneman's Thinking, Fast and Slow, Amos Tversky and Daniel Kahneman's Judgment under Uncertainty, Anne Treisman's Feature Integration Theory"
source_date: 2021
topic_tags:
  - psychology
  - cognition
  - attention
  - heuristics
  - decision making
---

## Early and Attenuated Bottleneck Models of Selective Attention

Experimental investigations into selective attention originated with Donald Broadbent (1958) following dichotic listening studies on air-traffic controllers. Broadbent formulated the **Early Selection Filter Model**, which posits that human information processing is constrained by a single, central, capacity-limited channel. In this architecture, all sensory inputs from multiple ears or eyes enter a parallel sensory buffer. To prevent cognitive overload, an all-or-none selective filter evaluates inputs based strictly on elementary physical acoustic cues (such as ear of arrival, pitch, or vocal volume). Only the attended sensory channel passes through the bottleneck to the higher-order perceptual and semantic analysis systems; unattended sensory channels are completely blocked and rapidly decay without semantic processing.

Broadbent’s early selection model was disproven by the "Cocktail Party Phenomenon" (Colin Cherry, Neville Moray): when an individual’s own name is spoken quietly in the unattended acoustic channel, the individual frequently detects it, proving that unattended stimuli can bypass the bottleneck to undergo semantic evaluation. In response, Anne Treisman (1964) formulated the **Attenuation Model of Attention**. Treisman replaced Broadbent’s rigid, all-or-none filter with a flexible **attenuator** that weakens (dampens) the volume or signal-to-noise ratio of unattended sensory streams without eliminating them completely. The attenuated signals proceed to a mental dictionary of word recognizers. Words possessing low permanent threshold activations—such as one's personal name, danger warnings ("fire"), or words primed by the immediate conversational context—fire and reach conscious awareness even when received in an attenuated, unattended state.

## Treisman's Feature Integration Theory and Visual Conjunction Search

To resolve how the human visual brain binds disparate sensory features (color, orientation, spatial frequency, motion) into unified object tokens, Anne Treisman and Garry Gelade (1980) formulated **Feature Integration Theory (FIT)**. The theory bifurcates visual processing into two sequential stages:
1. **The Preattentive Stage:** Visual features are extracted automatically, unconsciously, and in parallel across the entire visual field by specialized early visual feature maps in striate and extrastriate cortex. When a target differs from surrounding distractors along a single basic feature dimension (e.g., searching for a single red circle among fifty green circles), the target visual feature "pops out" effortlessly. Visual search time is rapid and invariant to the number of distractors (yielding a flat, zero-slope reaction time function).
2. **The Focused Attention Stage:** When a target is defined by a unique combination or conjunction of two or more shared features (e.g., searching for a red circle among red squares and green circles), parallel preattentive maps cannot resolve object identity. Focused spatial attention must be deployed sequentially as an attentional "spotlight" or glue, binding the co-localized color and shape features at specific spatial coordinates within a master map of locations. Conjunction searches require serial processing, resulting in a linear increase in reaction time as distractor set size grows. Under conditions of high cognitive load, brief display durations, or parietal lobe damage, the binding mechanism fails, generating **illusory conjunctions**—perceptual errors where observers correctly identify features present in the scene but bind them incorrectly (e.g., perceiving a green dollar sign when shown a green circle adjacent to a red dollar sign).

## Dual-Process Cognitive Architecture: System 1 and System 2

Human reasoning and judgment are organized through a dual-process cognitive architecture, conceptualized by Keith Stanovich and Richard West (2000) and popularized by Daniel Kahneman in *Thinking, Fast and Slow* (2011). The framework distinguishes between two qualitatively distinct modes of information processing:
- **System 1 (Fast / Intuitive):** Operates automatically, rapidly, implicitly, effortlessly, and unconsciously. System 1 relies on associative memory networks, emotional valences, and learned heuristic patterns to generate continuous interpretations of reality, involuntary impressions, gut reactions, and causal narratives. It operates in parallel, is difficult to disrupt or voluntarily suppress, and consumes negligible metabolic working memory capacity. System 1 executes automated expert tasks (such as driving on an empty highway, detecting hostility in a voice, or calculating $2 + 2$).
- **System 2 (Slow / Deliberative):** Operates deliberately, consciously, effortfully, slowly, and analytically. System 2 is rule-governed, logical, and reflexive, subserved by the prefrontal cortex and working memory. It is responsible for agency, complex calculations ($17 \times 24$), critical error-checking, counterfactual reasoning, and suppressing impulsive System 1 intuitions. However, System 2 is severely capacity-constrained, lazy, and metabolically expensive: when an individual is cognitively busy, tired, or under acute stress, System 2 defaults to accepting the intuitive, unverified outputs generated by System 1, exposing decision making to systematic cognitive biases.

## The Availability and Representativeness Heuristics

In their groundbreaking cognitive research program throughout the 1970s, Amos Tversky and Daniel Kahneman demonstrated that when humans make judgments under uncertainty, they do not utilize normative probability calculus; instead, they rely on heuristic mental shortcuts that reduce complex algorithmic calculations to simple associative evaluations:
- **The Availability Heuristic:** Individuals evaluate the frequency, probability, or likelihood of an event based on the cognitive ease with which concrete exemplars come to conscious mind. While frequency and cognitive accessibility are often correlated in nature, subjective availability is heavily distorted by non-statistical factors, including emotional vividness, recency of exposure, and dramatic media coverage. Consequently, people dramatically overestimate the mortality risks of sensational, visually memorable hazards (such as commercial airplane crashes, shark attacks, terrorist attacks, and homicides) while underestimating statistically common, non-dramatic causes of mortality (such as stroke, asthma, and diabetes).
- **The Representativeness Heuristic:** Individuals evaluate the probability that an unknown object, person, or event $A$ belongs to a conceptual category $B$ based on the degree to which $A$ resembles or matches the prototypical mental exemplar of $B$. When similarity is high, the probability is judged to be high, causing decision makers to completely ignore objective statistical base rates, sample size constraints, and the mathematical laws of chance.

## The Conjunction Fallacy and Base-Rate Neglect in Judgments

The distorting power of the representativeness heuristic was demonstrated by Tversky and Kahneman (1983) through the formulation of the classic **Linda Problem**, which exposes the **Conjunction Fallacy**:
Participants were presented with a personality sketch: "Linda is 31 years old, single, outspoken, and very bright. She majored in philosophy. As a student, she was deeply concerned with issues of discrimination and social justice, and also participated in anti-nuclear demonstrations." Participants were asked to rank the probability of several statements, including:
1. Linda is a bank teller ($T$).
2. Linda is a bank teller and is active in the feminist movement ($T \wedge F$).

Over eighty-five percent of participants—including university undergraduates and statistically trained graduate students—judged Statement 2 as more probable than Statement 1. This judgment represents a direct violation of the fundamental mathematical axiom of probability theory: the probability of a conjunction of two independent events cannot exceed the probability of either constituent event ($P(A \cap B) \le P(A)$). The detailed description of Linda matched the stereotypical mental prototype of a feminist activist, seducing System 1 into substituting a judgment of narrative plausibility and representative similarity for a judgment of statistical probability.

Representativeness simultaneously induces **Base-Rate Neglect**: when evaluating medical diagnostic tests or forensic evidence, decision makers evaluate positive test accuracy while ignoring the underlying prevalence (base rate) of the condition within the population, committing the prosecutor's fallacy and generating massive false positive misdiagnoses.

## Anchoring Dynamics and Contextual Framing Effects

Human judgment is systematically biased by contextual anchors and semantic frames:
- **Anchoring and Adjustment Heuristic (Tversky & Kahneman, 1974):** When making quantitative estimates, individuals start from an initial numerical value provided in the environment (the anchor) and adjust away from it to reach their final answer. However, adjustments are almost universally insufficient. In a classic demonstration, participants observed a rigged wheel of fortune stop at either the number 10 or 65, and were subsequently asked: "What percentage of African nations are members of the United Nations?" Participants exposed to the anchor of 10 gave an average estimate of 25%, whereas participants exposed to 65 gave an average estimate of 45%. Anchoring operates through two distinct cognitive mechanisms: System 1 semantic priming (selective accessibility of anchor-consistent factual memories) and System 2 insufficient adjustment (halting adjustment once the estimate enters a plausible range).
- **Framing Effects (Tversky & Kahneman, 1981):** Choices between identical objective outcomes shift radically depending on whether outcomes are semantically framed as gains (survival) or losses (mortality). In the classic **Asian Disease Problem**, participants chose between programs to combat an epidemic expected to kill 600 people:
  - *Gain Frame:* Program A ("200 people will be saved") vs. Program B ("1/3 probability that 600 people will be saved, 2/3 probability that no people will be saved"). Seventy-two percent chose risk-averse Program A.
  - *Loss Frame:* Program C ("400 people will die") vs. Program D ("1/3 probability that nobody will die, 2/3 probability that 600 people will die"). Seventy-eight percent chose risk-seeking Program D.
  The mathematical expected values are identical across all options, yet the semantic shift from lives saved to lives lost flipped preferences from risk aversion to risk seeking.

## Prospect Theory: Reference Dependence and the S-Shaped Value Function

In 1979, Daniel Kahneman and Amos Tversky published **Prospect Theory**, establishing an empirical mathematical framework that replaced classical Expected Utility Theory as the descriptive model of economic decision making under risk. Prospect Theory identified three core psychophysical properties governing human valuation:
1. **Reference Dependence:** Individuals evaluate outcomes not in terms of absolute terminal wealth assets ($W$), but as positive gains ($+x$) or negative losses ($-x$) defined relative to an internal psychological neutral reference point ($R$), typically the current status quo.
2. **Diminishing Marginal Sensitivity:** The psychological impact of an incremental change diminishes as the absolute magnitude moves further away from the reference point. The difference between gaining $100 and $200 feels substantially greater than the difference between gaining $1,100 and $1,200.
3. **The S-Shaped Value Function $v(x)$:**
   - In the domain of gains ($x > 0$), the value function is **concave** ($v''(x) < 0$), generating risk-averse behavioral preferences (preferring a guaranteed $500 over a 50% chance at $1,000).
   - In the domain of losses ($x < 0$), the value function is **convex** ($v''(x) > 0$), generating risk-seeking behavioral preferences (preferring a 50% chance of losing $1,000 over a guaranteed loss of $500).

## Non-Linear Probability Weighting and Loss Aversion Ratios

Prospect Theory establishes that the subjective value function is characterized by an asymmetrical kink at the reference point, embodying the foundational behavioral principle of **Loss Aversion**: "losses loom larger than gains." The value function is substantially steeper in the domain of negative losses than in the domain of positive gains:

$$\lambda = \frac{-v(-x)}{v(x)} \approx 2.0 \text{ to } 2.5$$

The subjective psychological pain experienced when losing $100 is approximately two to two-and-a-half times more intense than the subjective pleasure experienced when gaining $100. Loss aversion explains why individuals routinely reject coin-toss gambles offering a 50% chance to lose $100 unless the prospective gain exceeds $200 to $250. Loss aversion underpins the **Endowment Effect** (Richard Thaler): individuals demand significantly more money to part with an object they own than they would be willing to pay to acquire the identical object from scratch, because relinquishing the object is cognitively coded as a painful loss.

Furthermore, Prospect Theory replaces objective probabilities ($p$) with subjective **Decision Weights** $\pi(p)$ via an inverted-S weighting curve:
- People systematically **overweight small probabilities** ($\pi(p) > p$ for small $p$), explaining the simultaneous societal popularity of lottery tickets (seeking a minuscule chance of an immense gain) and flood insurance (seeking protection against a minuscule risk of catastrophic loss).
- People systematically **underweight moderate and high probabilities** ($\pi(p) < p$), producing the **certainty effect** where reducing risk from 100% to 99% induces severe psychological anxiety compared to reducing risk from 50% to 49%.

## Executive Control: Inhibitory Control, Set-Shifting, and Working Memory Updating

Executive function denotes the suite of top-down cognitive control processes subserved by the prefrontal cortex (PFC) that enable goal-directed behavior, flexible adaptation, and the override of automated, impulsive routines. Akira Miyake and colleagues (2000) established through latent variable structural equation modeling that executive function is characterized by unity and diversity across three distinct core subcomponents:
1. **Inhibitory Control:** The capacity to deliberately suppress dominant, prepotent, automated responses and resist internal or external interference. Clinically evaluated via the **Stroop Task**: participants are presented with color words printed in incongruent ink colors (e.g., the word "BLUE" printed in red ink) and instructed to name the ink color while ignoring the text. Because automated visual word reading in literate adults is highly overlearned, inhibiting the prepotent reading response requires intense activation of the anterior cingulate cortex (ACC) and dorsolateral prefrontal cortex, producing a robust reaction time latency cost (the Stroop interference effect).
2. **Cognitive Flexibility (Set-Shifting):** The ability to disengage from an established cognitive mindset or task rule and seamlessly transition to an alternative rule set. Evaluated via the **Wisconsin Card Sorting Test (WCST)**: participants sort stimulus cards according to color, shape, or number based on experimenter feedback; when the sorting rule changes unannounced, patients with dorsolateral prefrontal lesions exhibit severe **perseveration**, continuing to sort by the outdated rule despite receiving continuous negative feedback.
3. **Working Memory Updating:** The ongoing monitoring, gating, and revision of working memory contents, discarding outdated information and replacing it with incoming relevant data, evaluated via continuous $n$-back working memory tasks.
