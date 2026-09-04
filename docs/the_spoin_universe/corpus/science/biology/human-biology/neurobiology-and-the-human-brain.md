---
title: "Neurobiology and the Human Brain: Electrophysiology, Synaptic Transmission, Functional Neuroanatomy, and Systems Architecture"
kind: topic_source
category: science
sub_category: biology
scope: survey
source: Principles of Neural Science (Kandel et al., 6th ed.), Guyton and Hall Textbook of Medical Physiology (14th ed.)
source_date: 2024
topic_tags:
  - biology
  - neurobiology
  - human-brain
  - action-potentials
  - synaptic-transmission
  - cerebral-cortex
  - autonomic-nervous-system
---

# Neurobiology and the Human Brain: Electrophysiology, Synaptic Transmission, Functional Neuroanatomy, and Systems Architecture

## Resting Membrane Potential and Electrophysiological Gradients

Neuronal communication relies on the rapid, regulated modulation of the electrical potential across the neuronal plasma membrane.

In typical human neurons, the intracellular compartment is electrically negative relative to the extracellular fluid, resting stably at approximately **-70 millivolts (mV)**. The resting membrane potential is established and maintained by:
1. *Transmembrane Concentration Gradients:* Maintained by the electrogenic $Na^+/K^+$-ATPase pump (extruding 3 $Na^+$ for every 2 $K^+$ imported).
2. *Selective Permeability:* At rest, the neuronal membrane is 20 to 100 times more permeable to potassium than to sodium, due to open, non-gated **Inward-Rectifier and Two-Pore Potassium Leak Channels** ($K_{ir}$, $K_{2P}$). Potassium diffuses down its steep concentration gradient out of the cell until the negative electrical potential inside the membrane exactly balances the outward chemical driving force (described by the Nernst equilibrium potential for $K^+$, $E_K \approx -90\text{ mV}$). The resting membrane potential of -70 mV represents the weighted composite equilibrium of all permeable ions, modeled by the **Goldman-Hodgkin-Katz (GHK) Voltage Equation**.

## Action Potential Depolarization, Inactivation, and Repolarization

The action potential is an all-or-none, regenerative electrical impulse generated at the axon initial segment when graded excitatory post-synaptic potentials depolarize the local membrane past the firing threshold of approximately **-55 mV**:
1. **Phase 1: Rapid Depolarization (Upstroke):** Crossing threshold triggers the rapid opening of the activation gates of **Voltage-Gated Sodium Channels ($Na_v$)**. Sodium rushes down both its concentration and electrical gradients into the cytoplasm (the regenerative Hodgkin cycle). The membrane potential reverses polarity, overshooting toward the sodium equilibrium potential ($E_{Na} \approx +60\text{ mV}$), peaking at approximately **+35 to +40 mV**.
2. **Phase 2: Inactivation and Repolarization:** Within approximately one millisecond of opening, an intracellular hydrophobic peptide loop of the $Na_v$ channel (the IFM inactivation particle or "ball-and-chain") swings into the channel pore, closing the **Inactivation Gate** and terminating further $Na^+$ influx. Simultaneously, **Voltage-Gated Delayed-Rectifier Potassium Channels ($K_v$)** open in response to sustained depolarization. Potassium rushes out of the cell, repolarizing the membrane potential back toward negative values.
3. **Phase 3: Hyperpolarization (Undershoot):** Because $K_v$ channels close with a slight kinetic delay, potassium permeability remains transiently elevated, driving the membrane potential toward the $K^+$ equilibrium potential (-90 mV). The $Na^+/K^+$-ATPase and resting leak channels restore baseline potential.

## Absolute and Relative Refractory Periods

Neuronal excitability is regulated by two consecutive refractory intervals following an impulse:
- **Absolute Refractory Period:** Spans the upstroke through early repolarization. Voltage-gated $Na_v$ channels are either fully open or locked in their inactivated conformation; it is physically impossible to evoke a second action potential, regardless of stimulus magnitude. This imposes an upper limit on neuronal firing frequency (~1000 Hz) and enforces unidirectional forward propagation along the axon.
- **Relative Refractory Period:** Spans late repolarization through after-hyperpolarization. $Na_v$ channels have transitioned from inactivated back to closed resting states and are capable of reopening, but residual $K_v$ conductance and hyperpolarization hold the cell below threshold; a second action potential can be triggered only by a supra-threshold stimulus.

## Myelination and Saltatory Conduction

Axonal conduction velocity is governed by the length constant ($\lambda = \sqrt{r_m / r_i}$, where $r_m$ is membrane resistance and $r_i$ is internal axial resistance) and the time constant ($\tau = r_m \cdot c_m$, where $c_m$ is membrane capacitance). 

To achieve rapid signal transmission without evolving prohibitively thick axonal diameters, vertebrates evolved **Myelination**:
- Myelin is a lipid-rich, multi-layered spiraling sheath produced by **Schwann cells** in the Peripheral Nervous System (PNS) and **Oligodendrocytes** in the Central Nervous System (CNS; one oligodendrocyte can myelinate up to 50 separate axonal segments).
- Myelin increases transverse membrane electrical resistance ($r_m$) by orders of magnitude and dramatically decreases membrane capacitance ($c_m$), minimizing passive current leakage across the internodal membrane.
- Between adjacent myelin sheaths lie unmyelinated gaps measuring 1 to 2 micrometers, termed **Nodes of Ranvier**. At these nodes, $Na_v$ channels (specifically $Na_v1.6$) are clustered at exceptionally high density (~10,000 channels per $\mu m^2$), anchored by cytoskeletal proteins (Ankyrin-G, $\beta IV$-spectrin).
- **Saltatory Conduction:** When an action potential fires at a node, local depolarizing current travels passively, electrotonically, and near-instantaneously through the axoplasm of the myelinated internode, arriving at the next node with sufficient voltage to exceed threshold. The action potential appears to "jump" from node to node, increasing conduction velocity from ~0.5–2 m/s in unmyelinated C-fibers up to **80–120 m/s** in heavily myelinated $A\alpha$ motor and sensory proprioceptive axons.

## Presynaptic Calcium Influx and SNARE-Mediated Vesicular Exocytosis

Neuronal communication occurs primarily across chemical synapses via regulated exocytosis:
- When an action potential reaches the presynaptic axon terminal (bouton), membrane depolarization opens **Voltage-Gated Calcium Channels ($Ca_v2.1$ / P/Q-type and $Ca_v2.2$ / N-type)**.
- Calcium rushes into the bouton, elevating localized microdomain $[Ca^{2+}]$ from ~100 nmol/L to >100 $\mu$mol/L.
- Free calcium binds the calcium sensor **Synaptotagmin-1**, which triggers the assembly of the **SNARE Complex**—comprising the vesicular v-SNARE Synaptobrevin (VAMP) and the plasma membrane t-SNAREs Syntaxin-1 and SNAP-25.
- The SNARE bundle zips into a tight four-helix bundle, overcoming electrostatic repulsion to fuse the vesicle membrane with the presynaptic active zone, releasing neurotransmitters into the 20–40 nanometer synaptic cleft.

## Postsynaptic Ionotropic and Metabotropic Neurotransmission

Neurotransmitters released into the synaptic cleft act on two major classes of postsynaptic receptors:
- **Ionotropic Receptors (Ligand-Gated Ion Channels):** Multimeric protein complexes that form an integral ion pore. Neurotransmitter binding directly opens the pore, producing fast, millisecond synaptic currents:
  - *AMPA Receptors:* Gated by glutamate; permit rapid $Na^+$ influx, generating fast EPSPs.
  - *NMDA Receptors:* Gated by glutamate, but physically blocked by an extracellular magnesium ion ($Mg^{2+}$) at resting potentials. Depolarization expels the $Mg^{2+}$ block, allowing high-volume $Ca^{2+}$ influx. This activity-dependent calcium influx initiates calcium/calmodulin-dependent protein kinase II (CaMKII) cascades, driving **Long-Term Potentiation (LTP)**—the cellular basis of learning and memory.
  - *$GABA_A$ Receptors:* Pentameric channels gated by GABA; permit inward $Cl^-$ flux, hyperpolarizing the postsynaptic membrane to generate fast Inhibitory Post-Synaptic Potentials (IPSPs).
- **Metabotropic Receptors (G-Protein Coupled Receptors / GPCRs):** Seven-transmembrane receptors coupled to heterotrimeric G-proteins ($\alpha, \beta, \gamma$). Ligand binding activates second-messenger cascades (e.g., $G_s$ stimulating adenylate cyclase to raise cAMP; $G_i$ inhibiting cAMP; $G_q$ activating phospholipase C to cleave $PIP_2$ into $IP_3$ and DAG), producing prolonged, modulatory alterations in neuronal excitability and gene expression.
- **Termination of Signal:** Neurotransmitter action is rapidly terminated via high-affinity reuptake transporters (e.g., DAT, SERT, and astrocytic EAATs) or enzymatic cleavage (e.g., **Acetylcholinesterase (AChE)** in the synaptic cleft).

## Cerebral Cortical Laminae and Frontal Lobe Functional Zones

The human cerebral cortex forms an extensively folded mantle of gray matter (1.5 to 4.5 mm thick) characterized by gyri (crests) and sulci (grooves), which triples the available cortical surface area. The neocortex is organized into six horizontal cytoarchitectural laminae (Layers I through VI) and vertical functional columns.

The **Frontal Lobe** coordinates motor execution and executive cognition:
- *Primary Motor Cortex (Precentral Gyrus / Brodmann Area 4):* Origin of the pyramidal corticospinal tract, organized somatotopically as the **Motor Homunculus** (disproportionately massive cortical representations dedicated to the face, tongue, and hands).
- *Premotor Cortex and Supplementary Motor Area (Area 6):* Governs motor planning, postural stabilization, and complex bilateral movement sequencing.
- *Broca's Area (Opercular and triangular parts of the inferior frontal gyrus / Areas 44 and 45, typically in the left dominant hemisphere):* Coordinates the motor programming and syntactic sequencing of expressive speech. Lesions produce Broca's (expressive/non-fluent) aphasia: intact comprehension, but effortful, agrammatic speech output.
- *Prefrontal Cortex (PFC):* Dorsolateral PFC governs executive function, abstract reasoning, goal-directed planning, and working memory; Ventromedial and Orbitofrontal PFC govern risk appraisal, moral deliberation, and emotional self-regulation.

## Parietal, Temporal, and Occipital Sensory Processing Networks

Sensory reception and association are distributed across the remaining cortical lobes:
- **Parietal Lobe:**
  - *Primary Somatosensory Cortex (Postcentral Gyrus / Areas 3, 1, 2):* Receives tactile, proprioceptive, and nociceptive afferents via the thalamic ventral posterolateral (VPL) and posteromedial (VPM) nuclei, organized as the **Sensory Homunculus**.
  - *Posterior Parietal Lobules (Areas 5 and 7):* Integrates visual, somatosensory, and vestibular inputs for spatial attention and sensorimotor transformation. Lesions of the right parietal lobe produce **Hemispatial Neglect Syndrome** (inability to attend to the left visual and physical hemispace).
- **Temporal Lobe:**
  - *Primary Auditory Cortex (Transverse temporal gyri of Heschl / Areas 41 and 42):* Tonotopically organized acoustic reception.
  - *Wernicke's Area (Posterior superior temporal gyrus / Area 22, dominant hemisphere):* Receptive decoding of phonological and semantic linguistic inputs. Lesions produce Wernicke's (receptive/fluent) aphasia: impaired comprehension, with fluid, paraphasic "word salad" speech output. Connected to Broca's area via the **Arcuate Fasciculus**.
  - *Fusiform Gyrus (Occipitotemporal gyrus / Area 37):* Specialized for complex facial recognition; bilateral infarction produces **Prosopagnosia** (face blindness).
- **Occipital Lobe:**
  - *Primary Visual Cortex (Striate Cortex / Area 17 / V1):* Surrounds the calcarine sulcus, organized retinotopically to process visual field inputs. Projections split into the dorsal "where/how" parietal stream (spatial localization, motion) and ventral "what" temporal stream (object identification, color).

## The Limbic System: Hippocampal Consolidation and Amygdalar Valence

Beneath the cerebral mantle lie evolutionarily conserved subcortical networks coordinating memory, emotional valence, and homeostatic drives:
- **Hippocampus:** Located in the medial temporal lobe, structured as the trisynaptic circuit (Dentate Gyrus $\to$ CA3 $\to$ CA1 $\to$ Subiculum). Crucial for encoding and consolidating short-term declarative (episodic and semantic) memories into distributed neocortical networks. Bilateral hippocampal resection (as in the historic patient H.M.) produces permanent anterograde amnesia with preserved procedural memory. The subgranular zone of the dentate gyrus represents one of the few sites of adult mammalian neurogenesis.
- **Amygdala:** Situated immediately anterior to the hippocampus. Its basolateral nuclei integrate multi-modal sensory inputs to assign emotional valence, while the central nucleus projects to the hypothalamus and brainstem to orchestrate autonomic fear responses and stress hormone cascades.

## Basal Ganglia Circuitry: Direct, Indirect, and Modulatory Pathways

The basal ganglia constitute a subcortical loop that gates and modulates volitional movement, comprising the Striatum (Caudate Nucleus and Putamen), Globus Pallidus (external GPe and internal GPi), Subthalamic Nucleus (STN), and Substantia Nigra (pars compacta SNc and pars reticulata SNr):
- **Direct Pathway (Pro-Kinetic):** Motor cortex stimulates Striatum ($+$) $\to$ GABAergic striatal neurons directly inhibit GPi/SNr ($-$) $\to$ Disinhibits the Ventral Lateral/Ventral Anterior (VL/VA) Thalamus ($+$) $\to$ Thalamus excites Motor Cortex ($+$), **promoting movement initiation**. Driven by dopaminergic inputs from SNc acting on excitatory **$D_1$ Receptors**.
- **Indirect Pathway (Anti-Kinetic):** Cortex excites Striatum ($+$) $\to$ Striatal neurons inhibit GPe ($-$) $\to$ Disinhibits Subthalamic Nucleus ($+$) $\to$ STN fires glutamate to hyperactivate GPi/SNr ($+$) $\to$ Inhibits Thalamus ($-$) $\to$ Motor Cortex drive is suppressed, **inhibiting unwanted movement**. Dopamine from SNc inhibits this pathway via inhibitory **$D_2$ Receptors**.
- *Pathological States:* Degeneration of dopaminergic neurons in the Substantia Nigra pars compacta shifts the balance toward the indirect pathway, producing **Parkinson's Disease** (bradykinesia, resting tremor, rigidity). Conversely, degeneration of striatal GABAergic neurons projecting to GPe produces **Huntington's Disease** (hyperkinetic chorea).

## Sympathetic Nervous System: Thoracolumbar Architecture and Adrenergic Effectors

The Sympathetic Division of the Autonomic Nervous System maintains involuntary visceral homeostasis and mediates catabolic responses:
- Mediates the "fight-or-flight" response during physiological stress, exercise, or acute danger.
- *Anatomy:* Preganglionic cell bodies originate in the intermediolateral cell column (IML) of spinal cord segments **T1 through L2**. Short preganglionic myelinated fibers project to the bilateral sympathetic chain (paravertebral ganglia) or prevertebral ganglia (celiac, superior mesenteric, inferior mesenteric).
- *Neurochemistry:* Preganglionic axons release **Acetylcholine (ACh)** onto **Nicotinic ($N_N$)** receptors. Long postganglionic unmyelinated fibers project to target organs, releasing **Norepinephrine (NE)** onto adrenergic receptors:
  - *$\alpha_1$ Receptors:* Vascular smooth muscle contraction (vasoconstriction, elevates blood pressure).
  - *$\beta_1$ Receptors:* Cardiac sinoatrial node and ventricular myocardium (increases heart rate / chronotropy and contractility / inotropy).
  - *$\beta_2$ Receptors:* Bronchial smooth muscle (bronchodilation, increases alveolar airflow).
- *Adrenal Medulla:* Modified postganglionic neuroendocrine chromaffin cells innervated directly by preganglionic fibers; sympathetic stimulation releases Epinephrine (80%) and Norepinephrine (20%) directly into systemic circulation.

## Parasympathetic Nervous System: Craniosacral Architecture and Cholinergic Signaling

The Parasympathetic Division maintains anabolic "rest-and-digest" equilibrium, energy conservation, and visceral evacuation:
- *Anatomy:* Preganglionic cell bodies reside in brainstem cranial nerve nuclei (**CN III, VII, IX, and predominantly CN X / Vagus Nerve**) and sacral spinal cord segments **S2 through S4**. Long preganglionic fibers project to terminal or intramural ganglia situated directly adjacent to, or within the walls of, target organs.
- *Neurochemistry:* Preganglionic axons release **ACh** onto **Nicotinic ($N_N$)** receptors. Short postganglionic fibers release **ACh** onto tissue-specific **Muscarinic Receptors ($M_1$ through $M_5$)**:
  - *$M_2$ Receptors:* Located on the cardiac SA and AV nodes; coupled to $G_i$, opening $K_{ACh}$ channels to decrease heart rate (negative chronotropy) and conduction velocity.
  - *$M_3$ Receptors:* Located on visceral smooth muscle and exocrine glands; coupled to $G_q$, stimulating salivary and gastric secretion, intestinal peristalsis, pupillary constriction (miosis), and bladder detrusor muscle contraction.
