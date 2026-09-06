---
topic: Astronomy
description: The physics, mechanics, and observational architecture of the universe from planetary systems to cosmic large-scale structure
is_survey: true
subtopics:
  - title: Electromagnetic Radiation & Astronomical Instrumentation
    description: How astronomers capture and decode cosmic light across wavebands using telescopes, optics, detectors, and spectroscopy
    prerequisites: []
    sources:
      - astronomy/physics/astronomy/electromagnetic-radiation-spectroscopy-and-instrumentation.md
      - astronomy/physics/astronomy/tips-and-tricks.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: Celestial Mechanics & Orbital Dynamics
    description: The gravitational laws governing orbits, coordinate frames, perturbations, tidal forces, and multibody resonances
    prerequisites: []
    sources:
      - astronomy/physics/astronomy/celestial-mechanics-and-orbital-dynamics.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: The Solar System & Planetary Science
    description: Planetary formation, differentiation, atmospheres, magnetospheres, ring systems, and small body dynamics across the heliosphere
    prerequisites:
      - Electromagnetic Radiation & Astronomical Instrumentation
      - Celestial Mechanics & Orbital Dynamics
    sources:
      - astronomy/physics/astronomy/the-solar-system-and-planetary-science.md
      - astronomy/physics/astronomy/tips-and-tricks.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: Stellar Structure & Nuclear Fusion
    description: Hydrostatic equilibrium, energy transport mechanisms, thermodynamics, and interior nuclear fusion pathways of stars
    prerequisites:
      - Electromagnetic Radiation & Astronomical Instrumentation
    sources:
      - astronomy/physics/astronomy/stellar-structure-and-stellar-nucleosynthesis.md
    tiers:
      beginner:
        target_cards: 16
        card_types: { prose: 12, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: Stellar Evolution, Remnants & Compact Objects
    description: Post-main-sequence evolutionary tracks, supernovae, planetary nebulae, white dwarfs, pulsars, and black hole event horizons
    prerequisites:
      - Stellar Structure & Nuclear Fusion
    sources:
      - astronomy/physics/astronomy/stellar-evolution-remnants-and-the-hr-diagram.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 22
        card_types: { prose: 17, code: 0, diagram: 1, comparison: 3, ascii: 1 }

  - title: The Milky Way & The Interstellar Medium
    description: Galactic morphology, kinematics, stellar populations, dark matter halo evidence, and multi-phase gas-dust cycles
    prerequisites:
      - Stellar Evolution, Remnants & Compact Objects
    sources:
      - astronomy/physics/astronomy/galactic-astronomy-and-the-interstellar-medium.md
    tiers:
      beginner:
        target_cards: 16
        card_types: { prose: 12, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: Extragalactic Astronomy & Galaxy Evolution
    description: Galaxy classification, scaling relations, active galactic nuclei (AGN), quasars, and hierarchical merger assembly over cosmic time
    prerequisites:
      - The Milky Way & The Interstellar Medium
    sources:
      - astronomy/physics/astronomy/extragalactic-astronomy-and-cosmic-large-scale-structure.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: Cosmic Large-Scale Structure & The Cosmic Web
    description: Galaxy clusters, cosmic voids, filamentary networks, dark matter distribution, and gravitational lensing across the universe
    prerequisites:
      - Extragalactic Astronomy & Galaxy Evolution
    sources:
      - astronomy/physics/astronomy/extragalactic-astronomy-and-cosmic-large-scale-structure.md
    tiers:
      beginner:
        target_cards: 16
        card_types: { prose: 12, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: Observational Cosmology & The Distance Ladder
    description: Measuring cosmic scale, standard candles, expansion rate, the Hubble tension, and spacetime metric kinematics
    prerequisites:
      - Electromagnetic Radiation & Astronomical Instrumentation
      - Extragalactic Astronomy & Galaxy Evolution
    sources:
      - astronomy/physics/astronomy/observational-cosmology-and-the-cosmic-distance-ladder.md
      - astronomy/physics/astronomy/tips-and-tricks.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 14, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }

  - title: The Early Universe & Precision Cosmology
    description: The Hot Big Bang, cosmological inflation, Big Bang nucleosynthesis, recombination, and Cosmic Microwave Background physics
    prerequisites:
      - Cosmic Large-Scale Structure & The Cosmic Web
      - Observational Cosmology & The Distance Ladder
    sources:
      - astronomy/physics/astronomy/observational-cosmology-and-the-cosmic-distance-ladder.md
    tiers:
      beginner:
        target_cards: 16
        card_types: { prose: 12, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      intermediate:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
      advanced:
        target_cards: 20
        card_types: { prose: 16, code: 0, diagram: 1, comparison: 2, ascii: 1 }
---
