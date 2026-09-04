---
title: Electromagnetic Radiation, Spectroscopy, and Instrumentation
kind: topic_source
category: astronomy
sub_category: physics
scope: survey
source: Morgan-Keenan Classification System & W.W. Morgan & P.C. Keenan (Yerkes Spectral Atlas)
source_date: 2024
topic_tags: [astronomy, spectroscopy, blackbody-radiation, telescopes, adaptive-optics, morgan-keenan, diffraction-limit]
---

# Electromagnetic Radiation, Spectroscopy, and Instrumentation

## Blackbody Radiation Physics

Thermal radiation emitted by stars, gas clouds, and cosmic background fields approximates ideal blackbody radiators in local thermodynamic equilibrium (LTE). Three core physical laws describe this radiation:

1. **Planck's Radiation Law:** Defines the spectral radiance $B_\lambda(T)$ emitted per unit wavelength as a function of absolute temperature $T$:
   $$B_\lambda(T) = \frac{2hc^2}{\lambda^5} \frac{1}{e^{\frac{hc}{\lambda k_B T}} - 1}$$
   where $h$ is Planck's constant, $c$ is the speed of light, and $k_B$ is the Boltzmann constant.
2. **Wien's Displacement Law:** Taking the derivative of Planck's distribution reveals that the peak emission wavelength $\lambda_{max}$ is inversely proportional to temperature:
   $$\lambda_{max} T = b \quad (b \approx 2.89777 \times 10^{-3}\text{ m}\cdot\text{K})$$
   Hot stars ($T \approx 30,000\text{ K}$) emit primarily in the ultraviolet ($\lambda_{max} \approx 96\text{ nm}$); solar-type stars ($T \approx 5,778\text{ K}$) peak in green-blue optical light ($\lambda_{max} \approx 500\text{ nm}$); and the cosmic microwave background ($T = 2.7255\text{ K}$) peaks in microwaves ($\lambda_{max} \approx 1.06\text{ mm}$).
3. **The Stefan-Boltzmann Law:** Integrating Planck's law across all wavelengths yields the total bolometric flux $F$ radiated per unit surface area:
   $$F = \sigma T^4 \quad (\sigma \approx 5.6704 \times 10^{-8}\text{ W m}^{-2}\text{K}^{-4})$$
   For a spherical star of physical radius $R$ and effective temperature $T_{eff}$, total bolometric luminosity $L$ is:
   $$L = 4\pi R^2 \sigma T_{eff}^4$$

## Kirchhoff's Laws and Atomic Spectral Line Formation

In 1859, Gustav Kirchhoff established the three empirical laws governing spectral emission and absorption:

1. **Continuous Spectrum:** A hot, dense solid, liquid, or high-pressure gas emits a continuous spectrum across all wavelengths without interruption.
2. **Emission Line Spectrum:** A hot, low-density gas produces discrete bright emission lines at specific quantized wavelengths. When bound electrons undergo downward transitions between atomic energy levels ($E_2 \to E_1$), they emit photons with exact energies:
   $$\Delta E = E_2 - E_1 = h\nu = \frac{hc}{\lambda}$$
3. **Absorption Line Spectrum:** When continuous radiation traverses a cooler, low-density intervening gas, the atoms absorb photons matching their exact excitation energies. This imprints dark absorption lines (Fraunhofer lines) against the bright continuous spectrum.

Because each chemical element and ionization state possesses a unique electronic configuration, absorption lines function as spectroscopic fingerprints, revealing the chemical composition, atmospheric density, radial velocity (via Doppler shifts $\Delta\lambda/\lambda = v/c$), and magnetic fields (via Zeeman splitting) of distant stars.

## The Morgan-Keenan (M-K) Spectral Classification

Stars are classified systematically by surface temperature and atmospheric density via the **Morgan-Keenan (M-K) system**, combining an alphanumeric spectral sequence with Yerkes luminosity classes:

### The Temperature Sequence (OBAFGKM)
Divided into subclasses 0 (hottest) to 9 (coolest):
- **O ($> 30,000\text{ K}$, Blue):** Ionized helium (He II) absorption, weak neutral hydrogen Balmer lines.
- **B ($10,000 - 30,000\text{ K}$, Blue-White):** Neutral helium (He I) dominant, prominent hydrogen Balmer lines.
- **A ($7,500 - 10,000\text{ K}$, White):** Hydrogen Balmer lines reach maximum strength at A0 (e.g., Vega); neutral metals begin appearing.
- **F ($6,000 - 7,500\text{ K}$, Yellow-White):** Hydrogen weakens; singly ionized calcium (Ca II H and K lines) strengthens.
- **G ($5,200 - 6,000\text{ K}$, Yellow):** Strong ionized calcium lines, prominent neutral metal lines (e.g., the Sun: G2).
- **K ($3,700 - 5,200\text{ K}$, Orange):** Dominant neutral metallic lines, molecular bands (CH, CN) emerge.
- **M ($2,400 - 3,700\text{ K}$, Red):** Dominated by dense molecular bands, particularly titanium oxide (TiO).

### Luminosity Classes
Governed by atmospheric pressure and surface gravity broadening (giants have lower atmospheric pressures, producing narrower absorption lines than dense dwarfs):
- **Class Ia-O / Ia / Ib:** Hypergiants and Supergiants (e.g., Betelgeuse, Rigel).
- **Class II / III:** Bright Giants and Normal Giants (e.g., Arcturus: K1.5III).
- **Class IV:** Subgiants.
- **Class V:** Main Sequence Dwarfs (e.g., the Sun: G2V).
- **Class VII (or D):** Degenerate White Dwarfs.

## Telescope Optical Geometries and Angular Resolution

Astronomical telescopes serve two distinct optical functions: collecting photons and resolving spatial details:

- **Refracting Telescopes (Dioptrics):** Use transparent glass lenses. Large refractors suffer from **chromatic aberration** (different wavelengths refract at different angles, creating color halos), optical absorption in thick glass, and structural sagging because large lenses can only be supported along their perimeter.
- **Reflecting Telescopes (Catoptrics):** Use front-surface curved mirrors (typically parabolic or hyperbolic, as in the Ritchey-Chrétien design). Reflectors eliminate chromatic aberration and can be supported uniformly across their entire back surfaces, making them the universal baseline for all modern research telescopes.
- **Light-Gathering Power:** Scales directly with collecting area ($\text{LGP} \propto D^2$). Doubling mirror aperture quadruples the rate of photon collection.
- **The Diffraction Limit (Rayleigh Criterion):** Wave interference sets a fundamental physical limit on the minimum angular resolution $\theta$ (in radians) achievable by a circular aperture of diameter $D$ at wavelength $\lambda$:
  $$\theta = 1.22 \frac{\lambda}{D}$$
  Smaller $\theta$ indicates finer resolving capability.

## Atmospheric Seeing, Adaptive Optics, and Interferometry

Earth's turbulent atmosphere degrades optical astronomical observations. Random temperature and density fluctuations distort planar light waves into irregular wavefronts, causing point-source starlight to blur into a shifting seeing disc of $0.5 - 1.5\text{ arcseconds}$, canceling the theoretical diffraction advantage of large ground-based mirrors.

Astronomers bypass this limitation through two technological strategies:

1. **Adaptive Optics (AO):** Uses a wavefront sensor to analyze atmospheric distortion thousands of times per second (using light from a bright natural guide star or an artificial sodium laser guide star excited at 589 nm in the mesosphere). A computer calculates inverse phase corrections and commands piezo-electric actuators behind a deformable thin mirror to cancel the turbulence in real time, restoring diffraction-limited angular resolution to ground-based telescopes.
2. **Aperture Synthesis and Interferometry:** In the radio and sub-millimeter regimes (such as the Atacama Large Millimeter/submillimeter Array [ALMA] and Very Long Baseline Interferometry [VLBI]), signals from arrays of widely separated antennas are correlated. The effective angular resolution corresponds not to individual dish diameters, but to the maximum physical baseline $B$ separating the antennas ($\theta \sim \lambda / B$). The Event Horizon Telescope (EHT) linked global radio dishes across continents to achieve an effective aperture the size of Earth, resolving the microarcsecond event horizon shadows of Sagittarius A* and M87*.
