# HelioStock horaire

Module Python / Streamlit de pre-dimensionnement horaire pour un systeme :

- solaire thermique ;
- stockage intersaisonnier dans un champ de sondes BTES ;
- PAC geothermique sur champ de sondes ;
- deux usages industriels de prechauffage d'air exterieur.

Les deux besoins process sont :

1. haute temperature : air exterieur -> 60 C, prechauffe par le ballon solaire puis complete par appoint ;
2. basse temperature : air exterieur -> 25 C, couvert par PAC geothermique utilisant le champ comme source.

Le surplus solaire valorisable est injecte dans le champ de sondes, borne a `Tmax = 40 C` par defaut.

## Lancer la demo

Environnement recommande pour le deploiement :

- Python 3.11 ou 3.12 ;
- dependances installees depuis `requirements.txt` ;
- eviter Python 3.14 tant que la combinaison Streamlit/pandas/pygfunction n'est pas qualifiee.

```bash
cd heliostock_module
python -m streamlit run demo_app.py
```

La demo ouvre directement le module de calcul horaire solaire + stockage journalier + BTES + PAC + economie solaire/geothermie/appoint.
Le résultat technique principal est lu par défaut sur l'année finale d'une simulation champ de sondes de 25 ans.
Une projection physique multiannuelle répète la même météo et les mêmes besoins sur cette durée pour visualiser la dérive
thermique du champ de sondes. Cette projection est menée à la fois pour la géothermie seule et pour la géothermie avec
recharge solaire, avec le modele champ de sondes pygfunction.

Par defaut, la demo charge le fichier EPW Nantes embarque. L'interface permet aussi de choisir Angers :

```text
data/FRA_PL_Nantes.Atlantique.AP.072220_TMYx.zip
data/FRA_PL_Angers.Loire.AP.073901_TMYx.zip
```

Le profil de besoins doit etre charge par fichier Excel process 8760 h via l'interface Streamlit. Aucun fichier Excel de
besoin process n'est embarque dans le depot public. Sans upload 8760 h valide, le calcul n'est pas lance.

Les vrais profils industriels doivent rester locaux et ne doivent pas etre versionnes dans le depot public.

## Packaging

Avant de livrer une archive, verifier qu'elle ne contient pas `__pycache__/`, `.pytest_cache/` ni ancien projet imbrique
`heliostock_module/heliostock_module/`. Le depot doit contenir un seul package `heliostock/` actif afin d'eviter les
conflits d'import et de tests.

Pour le fichier Excel process actuellement supporte, le mapping est :

- `E besoin HT kWh` / `P besoin HT kW` -> besoin HT 60 C ;
- `E besoin BT kWh` / `P besoin BT kW` -> besoin BT 25 C.

## Integration dans une app Streamlit existante

```python
from heliostock.streamlit_module import render_heliostock_hourly

results_df = render_heliostock_hourly()
```

## Structure

- `heliostock/hourly_engine.py` : moteur de resolution horaire 8760 h.
- `heliostock/load_profiles.py` : construction des profils de besoins horaires et pre-dimensionnement de puissance BT.
- `heliostock/inputs.py` : dataclasses d'entrees utilisateur, validation legere et construction des configs de calcul.
- `heliostock/app_service.py` : couche applicative sans Streamlit, lance le calcul principal et les parametriques.
- `heliostock/postprocess.py` : conversions resultats horaires vers tableaux annuels, mensuels et monotones.
- `heliostock/charts.py` : graphiques Altair utilises par l'interface.
- `heliostock/scenarios.py` : execution des scenarios avec/sans solaire, economie, gains sondes et etudes parametriques.
- `heliostock/borefield_savings.py` : solveur d'economie equivalente de lineaire de sondes.
- `heliostock/streamlit_module.py` : orchestration legere de la page Streamlit.
- `heliostock/ui_forms.py` : rendu des panneaux de saisie et conversion en dataclasses d'entree.
- `heliostock/ui_results.py` : rendu des resultats physiques, diagnostics, onglets et etudes parametriques.
- `heliostock/ui_economics.py` : rendu dedie de l'onglet economie.
- `heliostock/economics.py` : calculs economiques solaire, geothermie PAC, appoint et cout cumule.
- `heliostock/epw_reader.py` : lecture d'un zip EPW horaire.
- `heliostock/engine.py` : definitions communes, configurations et fonctions physiques partagees.
- `ARCHITECTURE_HELIOSTOCK.md` : cartographie des couches et regles de separation.
- `NOTICE_MODELE_HELIOSTOCK.md` : notice détaillée des equations, hypotheses et bilans du modèle.

## Logique metier horaire

Pour chaque heure EPW, le calcul suit l'ordre suivant :

1. Calcul de la temperature du ballon solaire depuis son energie stockee.
2. Calcul du potentiel solaire thermique a la temperature de charge du ballon, avec `T_capteur ~= T_ballon + 10 K`.
3. Charge du stockage solaire journalier jusqu'a `Tmax ballon`, `80 C` par defaut.
4. Pertes horaires du ballon vers l'ambiance du local, `20 C` par defaut.
5. Decharge du ballon pour prechauffer le process HT, jusqu'a 60 C si le niveau de temperature le permet, puis appoint.
6. Calcul du solaire restant valorisable a plus basse temperature pour injection dans le champ de sondes.
7. Injection dans le champ, limitee par la puissance lineique admissible, la temperature de paroi et le rendement d'injection.
8. Couverture du process BT : air exterieur -> 25 C, par PAC geothermique, dans la limite de la puissance PAC retenue.
9. Calcul du COP PAC a partir de la temperature du champ apres injection solaire.
10. Appoint BT si le besoin horaire depasse la puissance PAC ou si la temperature source atteint la limite basse.
11. Extraction de chaleur du champ par la PAC, bornee par la Tmin source PAC operationnelle.
12. Mise a jour de l'historique thermique `pygfunction` par charge lineique nette.

L'analyse economique solaire thermique est calculee apres la simulation horaire, uniquement a partir du prechauffage
HT solaire issu du ballon journalier :

```text
energie_solaire_valorisee_solaire = prechauffage_HT_solaire
```

Le surplus injecte dans le BTES est valorise cote geothermie via l'aide geothermie et l'economie de lineaire de
sondes, afin d'eviter un double comptage des aides. Elle reprend ensuite une logique type HelioEco : CAPEX net
d'aide, cout de chaleur P1/P2/P4, economies annuelles et cashflow.
Une synthese multi-energies ajoute :

- les CAPEX P4 bruts, aides et nets par generateur ;
- les postes P1/P2/P4 en EUR/MWh par generateur ;
- le cout de chaleur par generateur et le cout global.

La reference de chaleur evitee pour le solaire est un appoint gaz. La geothermie beneficie d'une aide ADEME de
50 EUR/MWh.an sur la chaleur PAC, plafonnee a 65 % du CAPEX geothermie brut.
L'aide ADEME solaire est calculee uniquement sur le prechauffage HT solaire via ballon. Le surplus solaire injecte dans
le BTES n'est pas recompte cote solaire : il est valorise via la recharge geothermique et l'economie de lineaire de
sondes.

Le comparatif economique affiche maintenant 4 scenarios :

1. `Reference 100 % gaz` : HT et BT couverts par appoint gaz.
2. `Geothermie seule` : solaire force a 0 m2, HT gaz, BT par PAC geothermique + appoint gaz si necessaire.
3. `Geothermie + solaire meme sondes` : solaire HT + recharge BTES actifs, lineaire de sondes conserve.
4. `Geothermie + solaire sondes reduites` : solaire actif, lineaire equivalent reduit jusqu'a performance PAC proche
   de la geothermie seule.

Cette lecture suit la logique Dim A / Dim B / Dim C : la recharge solaire n'est pas analysee comme une chaleur solaire
autonome injectee, mais comme un service rendu au systeme geothermique. L'economie de sondes porte uniquement sur le
CAPEX sondes. Il n'y a pas d'economie P2 proportionnelle aux metres lineaires economises, car le P2 geothermie reste
lie a la puissance PAC, aux auxiliaires, a la regulation et a la maintenance.

Le cout solaire net est ventile par la methode A, au prorata energetique simple :

```text
E_solaire_total = E_solaire_HT + E_solaire_injectee_BTES
part_HT = E_solaire_HT / E_solaire_total
part_recharge = E_solaire_injectee_BTES / E_solaire_total
```

Les CAPEX/P2/P4 solaires sont ensuite affectes a la part HT et a la part recharge selon ce prorata.

Le P1 gaz est maintenant traité de façon cohérente entre les deux scénarios :

```text
P1 gaz utile moyen = P1 gaz PCI / rendement appoint gaz * facteur moyen d'inflation gaz
```

Ce même P1 gaz utile moyen est utilisé pour :

- la référence `100 % gaz` ;
- l'appoint gaz résiduel du scénario `Mix ENR`.

Le P2 gaz n'est plus nul. Il est calculé par défaut avec :

```text
P2 gaz annuel = puissance gaz installée * 10 EUR/kW.an
P2 gaz EUR/MWh = P2 gaz annuel / chaleur gaz utile annuelle
```

La même loi est appliquée à l'appoint gaz du `Mix ENR` et à la référence `100 % gaz`.

Le P1 électrique de la géothermie utilise maintenant une estimation prudente de l'électricité PAC complète :

```text
electricite_compresseur = chaleur_BT_PAC / COP_machine
auxiliaires_PAC = electricite_compresseur * 15 %
veille_regulation = 0,05 kW * heures
electricite_PAC_totale = electricite_compresseur + auxiliaires_PAC + veille_regulation
```

Cette correction couvre forfaitairement les pompes côté source/condenseur, la régulation et les petits auxiliaires PAC.
Le `P1'` auxiliaires solaires est conservé pour le solaire thermique. En revanche, aucune consommation spécifique de
pompes de transfert solaire vers BTES n'est ajoutée dans cette V0.

Deux études paramétriques optionnelles sont disponibles :

1. variation de la puissance PAC géothermique en `% Pmax BT`, avec solaire désactivé ;
2. variation de la surface solaire thermique.

Chaque point relance le calcul horaire et compare :

- le coût de chaleur du `Mix ENR`, en EUR/MWh ;
- le taux EnR global ;
- la couverture PAC BT pour l'étude PAC ;
- la couverture solaire HT pour l'étude solaire.

Dans l'étude PAC, le solaire thermique est forcé à 0 m² : le gaz couvre tout le besoin HT et le complément BT non
couvert par la PAC.

## Equations principales

### Besoin de prechauffage d'air

L'interface attend un profil horaire 8760 h importe par Excel. En amont, les besoins peuvent etre construits avec :

```text
Q_air = m_dot * Cp_air * max(0, T_cible - T_air_ext)
```

avec `T_cible_HT = 60 C` et `T_cible_BT = 25 C`.

### Rendement capteur solaire

Le rendement capteur est calcule heure par heure avec une forme EN12975 simplifiee :

```text
eta = eta0 - a1 * (T_mean - T_air) / G - a2 * (T_mean - T_air)^2 / G
```

`G` est l'irradiance moyenne horaire dans le plan des capteurs, en W/m2. Les donnees EPW sont lues en kWh/m2 sur
une heure ; numeriquement cela vaut des kW/m2 moyens, donc le code multiplie par 1000 pour obtenir `G`.
Il n'y a pas de plancher artificiel de nuit : si `G <= 0`, le rendement et la production solaire horaires valent `0`.

Deux rendements sont calcules :

- rendement de charge ballon avec une temperature capteur dependant de la temperature du ballon ;
- rendement stockage avec une temperature plus basse dependant du champ :

```text
T_mean_ballon = max(T_ambiance_ballon + approche_capteur, T_ballon + approche_capteur)
```

```text
T_mean_stockage = min(
  max(T_champ + marge_echangeur, Tmin_capteur_stockage),
  Tmax_capteur_stockage
)
```

Le solaire vers BTES peut donc avoir un meilleur rendement que la charge du ballon, car la temperature capteur est plus basse.

### Stockage solaire journalier

Le ballon solaire est resolu par bilan d'energie. L'energie interne affichee est l'energie stockee au-dessus de
l'ambiance du local :

```text
E_buffer = V_eau * 1,163e-3 * (T_ballon - T_ambiance)       [kWh]
E_buffer_max = V_eau * 1,163e-3 * (Tmax_ballon - T_ambiance) [kWh]
T_ballon = T_ambiance + E_buffer / (V_eau * 1,163e-3)
```

avec :

- `V_eau = surface_capteurs * volume_stockage_L_par_m2` ;
- `T_ambiance = 20 C` par defaut ;
- `Tmax_ballon = 80 C` par defaut, qui sert aussi de seuil de bascule vers BTES.

Le bilan horaire du ballon est :

```text
E_buffer_h+1 = E_buffer_h
             + energie_solaire_chargee_h
             - pertes_ballon_h
             - prechauffage_HT_solaire_h
```

Le ballon peut donc redescendre vers l'ambiance quand il n'y a pas de soleil ou quand le process le decharge.

### Allocation solaire horaire

```text
T_ballon = T_ambiance + E_buffer / C_ballon
T_capteur_ballon = max(T_ambiance + approche_capteur, T_ballon + approche_capteur)
eta_ballon = f(T_capteur_ballon, Tair_h, G_h)

potentiel_solaire_ballon_h = irradiation_h * surface * eta_ballon * rendement_systeme
solaire_vers_ballon_h = min(potentiel_solaire_ballon_h * facteur_charge, E_buffer_max - E_buffer)

T_prechauffage_solaire = min(
  T_process_HT,
  T_cible_prechauffage_solaire,
  max(Tair_h, T_ballon - approche_echangeur)
)

fraction_prechauffage = (T_prechauffage_solaire - Tair_h) / (T_process_HT - Tair_h)
prechauffage_HT_solaire = min(besoin_HT_h * fraction_prechauffage, E_buffer)
appoint_HT = besoin_HT_h - prechauffage_HT_solaire

fraction_restante = 1 - solaire_vers_ballon_h / potentiel_solaire_ballon_h
potentiel_stockage_BTES_h = irradiation_h * surface * eta_stockage_BTES * rendement_systeme * fraction_restante
injection_BTES = min(
  potentiel_stockage_BTES_h * rendement_injection,
  puissance_lineique_injection_max,
  limite_temperature_paroi
)
solaire_non_valorise = potentiel_stockage_BTES_h - injection_BTES
```

### Champ de sondes BTES avec pygfunction

HelioStock utilise uniquement `pygfunction` pour le champ de sondes. Le champ est pilote par la charge lineique nette :

```text
q_net_W_m = q_extraction_W_m - q_injection_W_m
q_extraction_W_m = Q_sol_extrait_kWh * 1000 / L_total_sondes_m
q_injection_W_m = Q_sol_injecte_kWh * 1000 / L_total_sondes_m
```

Convention : extraction PAC positive, injection solaire negative dans l'historique pygfunction.

### PAC geothermique

L'interface commence par le pré-dimensionnement PAC + sondes :

```text
P_PAC = Pmax_BT * ratio_PAC
```

avec `ratio_PAC` saisi en `% Pmax BT`.

Les hypothèses PAC du pré-dimensionnement peuvent ensuite être reprises telles quelles dans le calcul horaire ou
modifiées dans le bloc `Données PAC géothermique du calcul horaire`.

Le COP depend de la temperature fluide source PAC :

```text
COP = eta_PAC * T_cond,K / (T_cond,K - T_evap,K)
T_cond ~= T_cible_BT + approche_condenseur
T_evap ~= T_source_PAC - approche_evaporateur
T_source_PAC ~= T_paroi_forage - q_extraction_W_m * Rb_eff
```

Les valeurs par defaut sont volontairement conservatrices :

```text
eta_PAC = 54 %
approche_condenseur = 2 K
approche_evaporateur = 3 K
COP min = 2
COP max = 8
```

Le code conserve le denominateur physique `T_cond - T_evap`.

La puissance PAC est dimensionnee par un selecteur `P PAC = % Pmax BT`. Si le besoin horaire BT depasse cette puissance,
le excedent est affecte a l'appoint BT.

### Pre-dimensionnement des sondes

Le champ de sondes peut etre pre-dimensionne avant simulation a partir de la puissance PAC et du COP, sur le modele de
la matrice d'opportunite geothermie :

```text
P_sous_sol = P_PAC * (COP - 1) / COP
Q_sous_sol = Q_BT_PAC * (COP - 1) / COP
L_sondes = max(P_sous_sol * 1000 / ratio_W_ml, Q_sous_sol * 1000 / ratio_kWh_ml_an)
```

La longueur requise est arrondie aux 10 m superieurs, puis convertie en nombre de sondes avec la profondeur unitaire.
Les ratios par defaut sont `40 W/ml` et `60 kWh/ml.an`, avec facteur de securite `1,20`.
Les plages de lecture recommandees sont environ `35 a 45 W/ml` et `55 a 70 kWh/ml.an`, modifiables dans l'interface.

La chaleur livree par la PAC est separee en deux postes :

```text
Chaleur BT livree = chaleur extraite du champ + electricite PAC
electricite_PAC = Chaleur BT livree / COP
chaleur_extraite_champ = Chaleur BT livree - electricite_PAC
```

Si la puissance PAC, la puissance lineique d'extraction ou `Tmin source` limitent le fonctionnement, la chaleur BT livree par PAC est limitee et un appoint BT est affiche.

## Flux affiches

L'interface Streamlit expose notamment :

- un tableau annuel de synthese ;
- une comparaison horaire `sans solaire / avec solaire` ;
- la productivite solaire valorisee, en kWh/m2.an ;
- la consommation annuelle d'appoint ;
- le taux EnR global du projet, en considerant appoints et electricite PAC comme non EnR ;
- le taux de couverture solaire annuel et mensuel du besoin HT ;
- une estimation de l'economie equivalente de longueur de sondes a COP annuel equivalent ;
- une courbe annuelle de temperature du stockage solaire journalier ;
- une courbe de rendement capteur horaire pour la charge du ballon ;
- une monotone synchronisee des besoins HT/BT et des couvertures solaire/geothermie, avec tri par reference choisie ;
- des monotones empilees type mix energetique : solaire thermique + appoint pour HT, geothermie PAC + appoint pour BT ;
- la repartition solaire : charge ballon / prechauffage HT / injecte BTES / non valorise ;
- les flux mensuels du sous-sol : injection solaire positive, extraction PAC negative, bilan net sol ;
- l'evolution multiannuelle du champ de sondes : temperature source/paroi min/max/fin de mois, heures sous Tmin source et
  comparaison géothermie seule / géothermie + recharge solaire ;
- la couverture des besoins HT et BT ;
- le detail PAC : chaleur extraite du champ / electricite PAC ;
- l'etat du champ : injection, extraction, q_W/m, temperature paroi forage, temperature source PAC.
- un onglet économie solaire : CAPEX brut/net, aide ADEME, coût solaire, temps de retour brut, cashflow cumulé.

## Economie solaire thermique

Le CAPEX solaire thermique est calculé par la loi surfacique fournie :

```text
CAPEX = S * coût_unitaire(S)

si S <= 100    : coût_unitaire = 1500
si S <= 1000   : coût_unitaire = 1500 - 0,5556 * (S - 100)
si S <= 1500   : coût_unitaire = 1000 - 0,35 * (S - 1000)
si S > 1500    : coût_unitaire = -159,1 * ln(S) + 1990,2
```

L'aide ADEME est calculée selon la formule fournie et plafonnée par :

```text
aide_totale <= 65 % du CAPEX brut
```

Mapping des variables Excel dans le code :

- `S` = surface capteurs ;
- `X9` = énergie solaire valorisée annuelle, MWh/an ;
- `Hypothèses!D13` = aide énergie, €/MWh.an ;
- `X17` = CAPEX brut ;
- `X19` = autres aides publiques déjà acquises.

Le coût solaire affiché est :

```text
coût_solaire = P1_auxiliaires + P2_maintenance + P4_investissement_net
```

## Import obligatoire des besoins horaires

Le calcul physique fonctionne systematiquement sur un profil horaire 8760 h. Le fichier Excel importe doit contenir
directement les puissances ou energies horaires :

```text
P besoin HT kW ou E besoin HT kWh -> besoin HT 60 C
P besoin BT kW ou E besoin BT kWh -> besoin BT 25 C
```

Sans fichier Excel 8760 h valide, le calcul n'est pas lance.

Le stockage journalier HT est represente par une capacite energetique au-dessus de l'ambiance :

```text
Capacite ballon HT = surface capteurs * L/m2 * 1,163 Wh/L.K * (Tmax_ballon - T_ambiance)
```

Le solaire ne couvre plus directement le process HT. Il charge le ballon, le ballon prechauffe le process, puis
`appoint_HT` couvre le complement jusqu'a 60 C. Le BTES est charge uniquement lorsque le ballon atteint `Tmax ballon`
et ne peut plus absorber toute la ressource solaire disponible. La ressource solaire restante est alors recalculee a
temperature de stockage pour l'injection BTES.

## Limites actuelles

- calcul horaire EPW, avec import obligatoire d'un profil process 8760 h ;
- moteur champ de sondes unique base sur `pygfunction`, sans backend alternatif silencieux ;
- charges envoyees au champ en W/m, avec extraction PAC positive et injection solaire negative ;
- chaleur extraite du sol = chaleur BT livree par PAC - electricite compresseur ;
- temperature source PAC estimee par `T_paroi_forage - q_extraction * Rb_eff` ;
- couplage PAC/BTES explicite horaire, avec quelques iterations locales sur le COP ;
- pas encore un dimensionnement reglementaire de champ de sondes ;
- geometrie automatique approximative si aucun plan de champ reel n'est fourni ;
- pas de dimensionnement hydraulique ni pertes reseau detaillees ;
- les besoins process ne sont pas encore calcules depuis des debits horaires.

`pygfunction` calcule la derive thermique du champ a partir de l'historique horaire net. Les limites PAC viennent de la
puissance PAC installee, des puissances lineiques admissibles, de `Tmin source` et du COP minimum.

## Enseignements issus de Miceli et al. 2026 sur les BTES solaires

L'article de Miceli et al. 2026, "Modelling of borehole thermal energy storages: A g-function approach with a novel load
aggregation scheme", confirme l'interet des g-functions pour simuler rapidement des champs de sondes et BTES sur de
longues periodes. Il rappelle aussi que le point critique n'est pas uniquement le temps de calcul pygfunction : la gestion
de l'historique des charges thermiques devient centrale.

Pour les systemes solaires + BTES, les alternances entre injection estivale et extraction hivernale sont fortes. Une
agregation trop brutale peut moyenner des periodes de signes opposes et deplacer les temperatures lors des transitions
charge/decharge. Un controle d'erreur sur l'agregation est donc preferable a une agregation geometrique fixe.

HelioStock conserve pour l'instant le comportement robuste de production : `pygfunction` avec agregation Claesson-Javed.
Le code ajoute toutefois un diagnostic des signes de charge, du nombre de transitions injection/extraction, du ratio
injection/extraction et du type de fonctionnement du champ. Le mode `error_control_placeholder` reserve une architecture
pour une future agregation controlee par erreur ; il ne change pas encore le calcul physique.

Limites a garder en tete : `pygfunction` ne represente pas directement l'isolation superieure du stockage, les conditions
aux limites complexes, l'heterogeneite verticale detaillee, l'hydraulique serie/parallele fine de type MIFT ni l'inertie
detaillee tube/coulis a court terme. HelioStock reste donc un outil de predimensionnement d'opportunite, pas un jumeau
numerique detaille.

## Bibliotheque capteurs

Le capteur par defaut de l'interface est :

```text
Fabricant : SunOptimo
Modele : 245V
eta0 = 82,4 %
a1 = 2,905 W/m2.K
a2 = 0,030 W/m2.K2
```

Les coefficients restent modifiables dans l'interface.

## Import du besoin process

L'interface accepte un fichier Excel process. Le format recommande est un profil 8760 h avec :

```text
P besoin HT kW ou E besoin HT kWh -> besoin HT 60 C
P besoin BT kW ou E besoin BT kWh -> besoin BT 25 C
```

Les anciens formats journaliers ou mensuels ne sont plus acceptes dans l'interface. Les fichiers de besoins reels sont
ignores par Git via `.gitignore` et doivent rester locaux.

Le calcul ne se lance qu'apres clic sur le bouton `Lancer le calcul`, avec une barre de progression.

Les valeurs du fichier 8760 h sont utilisees directement, sans recalage par coefficient dans l'interface.

## Ecarts et points communs avec un outil classique de dimensionnement de champ de sondes

Points communs :

- HelioStock simule le champ de sondes sur une trajectoire multiannuelle, 25 ans par defaut.
- Le backend champ de sondes est exclusivement `pygfunction`.
- Les charges sont appliquees en W/m sur la longueur totale de sondes.
- Les resultats techniques principaux sont lus sur l'annee finale par defaut.
- Les indicateurs surveillent temperatures source, paroi forage, flux lineiques, COP, SPF et couverture PAC.

Specificites HelioStock :

- le besoin est separe entre process HT et BT ;
- le solaire thermique charge d'abord un ballon HT journalier ;
- l'injection BTES n'est autorisee qu'apres saturation du ballon solaire ;
- la recharge solaire est analysee comme un service rendu au systeme geothermique, pas comme une chaleur solaire injectee principale ;
- l'economie compare reference gaz, geothermie seule, geothermie + solaire meme lineaire et geothermie + solaire avec reduction de sondes.

Seuils et temperatures :

- le critere GMI est affiche avec `Tmin = -3 C` et `Tmax = +40 C` par defaut ;
- la Tmin source PAC operationnelle reste distincte, `5 C` par defaut, pour garder une marge prudente ;
- `T_paroi_forage_C`, `T_source_PAC_pour_COP_C`, `T_source_PAC_fin_heure_C`, `T_evaporateur_PAC_C` et `T_fluide_injection_C` ne representent pas la meme grandeur ;
- le couplage horaire est explicite : la PAC est pilotee avec la temperature disponible pendant l'heure, puis la temperature fin d'heure est obtenue apres application de la charge `pygfunction`.

Limites d'usage :

- le COP est une loi Carnot degradee simplifiee ;
- la geometrie automatique du champ influence fortement les interactions et reste un predimensionnement ;
- HelioStock ne remplace pas une etude geothermique detaillee avec TRT, geometrie reelle, hydraulique, pertes reseau et ingenierie dediee.

