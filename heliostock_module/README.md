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

```bash
cd heliostock_module
python -m streamlit run demo_app.py
```

La demo ouvre directement le module de calcul horaire solaire + stockage journalier + BTES + PAC + economie solaire/geothermie/appoint.
Le résultat principal reste une simulation 8760 h annuelle. Une projection physique multiannuelle répète ensuite la
même météo et les mêmes besoins sur la durée d'analyse économique, 20 ans par défaut, pour visualiser la dérive
thermique du champ de sondes. Cette projection est menée à la fois pour la géothermie seule et pour la géothermie avec
recharge solaire, avec le même moteur BTES sélectionné.

Par defaut, la demo charge le fichier EPW Nantes embarque. L'interface permet aussi de choisir Angers :

```text
data/FRA_PL_Nantes.Atlantique.AP.072220_TMYx.zip
data/FRA_PL_Angers.Loire.AP.073901_TMYx.zip
```

Le profil de besoins peut etre charge par fichier Excel process via l'interface Streamlit. Aucun fichier Excel de besoin
process n'est embarque dans le depot public. Sans upload, l'interface propose seulement un tableau mensuel editable de
secours, reparti ensuite sur les heures EPW.

Les vrais profils industriels doivent rester locaux et ne doivent pas etre versionnes dans le depot public.

Pour le fichier Excel process actuellement supporte, le mapping est :

- `E etuve recalee kWh` / `P etuve recalee kW` -> besoin HT 60 C ;
- `E cabines recalee kWh` / `P cabines recalee kW` -> besoin BT 25 C.

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
7. Injection dans le champ, limitee par la capacite thermique restante, le rendement d'injection et `Tmax champ`.
8. Couverture du process BT : air exterieur -> 25 C, par PAC geothermique, dans la limite de la puissance PAC retenue.
9. Calcul du COP PAC a partir de la temperature du champ apres injection solaire.
10. Appoint BT si le besoin horaire depasse la puissance PAC ou si le champ n'a pas assez d'energie au-dessus de `Tmin champ`.
11. Extraction de chaleur du champ par la PAC, bornee par `Tmin champ`.
12. Relaxation thermique horaire du champ vers la temperature naturelle du sol.

L'analyse economique solaire thermique est calculee apres la simulation horaire, uniquement a partir du prechauffage
HT solaire direct :

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
L'aide ADEME solaire est calculee uniquement sur le prechauffage HT solaire direct. Le surplus solaire injecte dans
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

L'interface laisse encore saisir directement les besoins en kWh/mois, mais la logique physique attendue en amont est :

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
  capacite_restante_champ
)
solaire_non_valorise = potentiel_stockage_BTES_h - injection_BTES
```

### Stockage BTES simplifie

Le champ est represente par une capacite thermique equivalente :

```text
V_sol = nombre_sondes * profondeur * espacement^2 * facteur_volume
E_stock = V_sol * rhoCp_sol * (T_champ - T_sol_initial)
T_champ = T_sol_initial + E_stock / (V_sol * rhoCp_sol)
```

Le bilan horaire est :

```text
E_stock_h+1 = E_stock_h
            + energie_injectee_h
            - energie_extraite_PAC_h
            - pertes_vers_sol_h
            + recharge_naturelle_si_champ_froid_h
```

La relaxation horaire est orientee vers `T_sol_initial` :

- si `T_champ > T_sol_initial`, le champ perd de la chaleur vers le sol ;
- si `T_champ < T_sol_initial`, le sol environnant recharge naturellement le champ.

Le champ est borne entre `Tmin champ` et `Tmax champ`.

### PAC geothermique

L'interface commence par le pré-dimensionnement PAC + sondes :

```text
P_PAC = Pmax_BT * ratio_PAC
```

avec `ratio_PAC` saisi en `% Pmax BT`.

Les hypothèses PAC du pré-dimensionnement peuvent ensuite être reprises telles quelles dans le calcul horaire ou
modifiées dans le bloc `Données PAC géothermique du calcul horaire`.

Le COP depend de la temperature du champ :

```text
COP = eta_PAC * T_cond,K / (T_cond,K - T_evap,K)
T_cond ~= T_cible_BT + approche_condenseur
T_evap ~= T_champ - approche_evaporateur
```

Les valeurs par defaut sont volontairement conservatrices :

```text
eta_PAC = 45 %
approche_condenseur = 7 K
approche_evaporateur = 3 K
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
Les ratios par defaut sont `60 W/ml` et `115 kWh/ml.an`, modifiables dans l'interface.

La chaleur livree par la PAC est separee en deux postes :

```text
Chaleur BT livree = chaleur extraite du champ + electricite PAC
electricite_PAC = Chaleur BT livree / COP
chaleur_extraite_champ = Chaleur BT livree - electricite_PAC
```

Si le champ ne contient pas assez d'energie disponible au-dessus de `Tmin champ`, la chaleur BT livree par PAC est limitee et un appoint BT est affiche.

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
- les flux mensuels du sous-sol : injection solaire positive, extraction PAC negative, recharge naturelle ;
- l'evolution multiannuelle du champ de sondes : temperature min/max/fin de mois, energie stockee, heures a Tmin et
  comparaison géothermie seule / géothermie + recharge solaire ;
- la couverture des besoins HT et BT ;
- le detail PAC : chaleur extraite du champ / electricite PAC ;
- l'etat du champ : injection, extraction, pertes, recharge naturelle, temperatures.
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

## Limite actuelle des besoins horaires

Si aucun fichier Excel process n'est chargé, les besoins HT/BT restent saisis en kWh/mois puis repartis uniformement
sur les heures de chaque mois. Avec le fichier Excel process, le profil est reconstruit à partir d'un calendrier journalier
et d'heures de fonctionnement, mais ce n'est pas encore un fichier 8760 h natif.

Le stockage journalier HT est represente par une capacite energetique au-dessus de l'ambiance :

```text
Capacite ballon HT = surface capteurs * L/m2 * 1,163 Wh/L.K * (Tmax_ballon - T_ambiance)
```

Le solaire ne couvre plus directement le process HT. Il charge le ballon, le ballon prechauffe le process, puis
`appoint_HT` couvre le complement jusqu'a 60 C. Le BTES est charge uniquement lorsque le ballon atteint `Tmax ballon`
et ne peut plus absorber toute la ressource solaire disponible. La ressource solaire restante est alors recalculee a
temperature de stockage pour l'injection BTES.

## Limites actuelles

- calcul horaire EPW, avec import possible d'un profil process 8760 h ;
- BTES represente par volume equivalent de sol en mode initial ;
- backend `pygfunction` experimental disponible dans l'interface pour calculer une temperature source issue des
  g-functions, avec fallback automatique vers le modele equivalent si la librairie n'est pas installee ;
- pertes du champ modelisees par relaxation horaire vers la temperature naturelle du sol ;
- pas de dimensionnement hydraulique ni pertes reseau detaillees ;
- les besoins process ne sont pas encore calcules depuis des debits horaires ;

Le mode `pygfunction` remplace la temperature source utilisee pour le COP PAC. Le bilan d'energie equivalent reste
conserve pour les limites d'injection/extraction et les bornes `Tmin/Tmax`, ce qui permet de revenir au modele initial
sans modifier les autres parametres.

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
P etuve recalee kW ou E etuve recalee kWh -> besoin HT 60 C
P cabines recalee kW ou E cabines recalee kWh -> besoin BT 25 C
```

Un ancien format journalier reste supporte : le module reconstruit alors un profil horaire en appliquant les puissances
sur les heures de fonctionnement, par defaut `5h-21h`.

Sans upload, l'interface bascule sur un tableau mensuel editable. Les fichiers de besoins reels sont ignores par Git via
`.gitignore` et doivent rester locaux.

Le calcul ne se lance qu'apres clic sur le bouton `Lancer le calcul`, avec une barre de progression.

Pour l'ancien format journalier, les besoins importes peuvent etre recales par coefficients :

```text
k cabines = 0,821
k etuve = 0,955
```

