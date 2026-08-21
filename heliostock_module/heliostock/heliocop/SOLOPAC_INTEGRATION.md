# Audit SoloPAC 1.1 et intégration dans HelioCOP

Source auditée : archive `SoloPAC_1_1.zip` transmise, comprenant notamment `Aide/AideSoloPAC.pdf`, `Aide/LivretSocolPacSolaire.pdf`, les fichiers XML PAC/capteurs et les cas exemples.

## Points retenus pour HelioCOP

1. **ECS2 devient la référence complète**, y compris le bouclage.
   - Le livret SOCOL ECS2 indique que la PAC solaire assure quasi-intégralement l'ECS et les pertes de bouclage.
   - Dimensionnement indicatif : `PDIM = PECS + PBoucl` puis `PnomPAC = 0,7*PECS + PBoucl`.
   - Cela corrige la V1.3 qui laissait le bouclage en dehors de la puissance PAC.

2. **Surface de source confirmée par SOCOL**.
   - Non vitré : 4 à 6 m²/kW PAC.
   - PVT : 3 à 6 m²/kW PAC.
   - Les valeurs de travail HelioCOP issues des REX (5 et 4,5 m²/kW PAC) sont cohérentes et restent les valeurs par défaut.

3. **Données PAC XML SoloPAC réutilisées comme références**.
   - HelioPAC 8/10/12/14 kW.
   - Giordano SPC20/SPC30/SPC50.
   - COP et puissance absorbée B10/W45 et B10/W65, limites de températures, débits et circulateurs.
   - Le noyau RE2020 de SoloPAC n'est pas copié : HelioCOP affiche seulement un repère B10/W60 par interpolation linéaire clairement identifié comme simplifié.

4. **Données capteurs WISC intégrées**.
   - HelioPAC Solerpool : 2,50 m²/unité.
   - Giordano Capteur4N : 4,70 m²/unité.
   - Dualsun DSTI/DSTN : 1,95 m²/unité.
   - Les coefficients WISC sont conservés pour le futur moteur dynamique.

5. **Indicateurs SOCOL intégrés dans le bilan simplifié**.
   - `FSAV = 1 - (WPACSolaire + Qappoint)/(QPACSolaire + Qappoint)`
   - `COPmoyen = QPACSolaire/WPACSolaire`
   - `FPAC = QPACSolaire/(QPACSolaire + Qappoint)`
   - Le cas exemple `ECS2_Nantes` fourni avec SoloPAC permet un test : FSAV ≈ 0,65, COP ≈ 3,02, FPAC ≈ 0,97.

6. **Usage industriel confirmé comme pertinent**.
   - Le livret cite explicitement les usages industriels/agricoles avec préchauffage à environ 60 °C, dont l'eau de lavage.
   - Pour ces cas, HelioCOP conserve son moteur direct sur profil 8760 h plutôt que de fabriquer un équivalent en logements standards.

## Points laissés au futur moteur dynamique

- matrice PAC complète avec interpolation/extrapolation RE2020 ;
- température réelle à l'évaporateur issue du champ solaire ;
- modèle WISC horaire avec vent et ciel ;
- stratification réelle des zones prioritaire/préchauffage ;
- logique V1/V2 ECS2 ;
- appoint dynamique ;
- pertes des ballons et réseaux ;
- marches/arrêts et modulation.
