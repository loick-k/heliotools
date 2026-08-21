# HelioCOP V1.5 — notice de calcul et traçabilité

## 1. Périmètre

HelioCOP est un outil de **prédimensionnement pour note d'opportunité**. Deux moteurs sont disponibles :

- **Logement collectif** : besoins par typologie de logements puis méthode COSTIC §2.3.2 adaptée au **schéma ECS2 SOCOL** pour le couple stockage / puissance PAC ;
- **Station de lavage poids lourds / usage process** : lecture directe d'un **profil thermique horaire 8760 h** et test des couples réels PAC / stockage.

Dans les deux cas, le résultat est destiné à être affiné par une simulation dynamique plus détaillée.

Références principales intégrées à cette version :

- COSTIC, *Le dimensionnement des systèmes de production d'eau chaude sanitaire en habitat individuel et collectif*, juin 2019, §2.3.2 ;
- SOCOL, *Livret PAC Solaire*, édition 2023, notamment §3.3 « ECS2 : Production d'ECS avec stockage en ECS » ;
- SoloPAC 1.1, aide du 10 juin 2026 et fichiers XML de caractéristiques PAC/capteurs fournis dans l'archive `SoloPAC_1_1.zip`.

## 2. Schéma hydraulique de référence : ECS2

HelioCOP retient le **schéma ECS2** comme architecture de référence : production d'ECS par PAC solaire avec une **zone prioritaire** et une **zone de préchauffage**.

Le livret SOCOL précise que le système PAC solaire ECS2 doit assurer quasi intégralement :

- l'ECS soutirée ;
- l'énergie nécessaire à la compensation des pertes de bouclage sanitaire.

L'appoint reste présent mais son recours annuel doit être marginal. La cible est notamment un **FPAC supérieur à 90 %**.

Pour la note d'opportunité, HelioCOP représente le stockage par **deux ballons identiques**, un pour chaque zone. Cette simplification est cohérente avec ECS2 mais n'est pas la seule architecture admise par SOCOL : un ballon unique stratifié ou plusieurs ballons montés en série dans chaque zone sont également possibles.

Le livret précise qu'en cas de ballon unique, une hauteur `H ≥ 3 × diamètre` est recommandée pour favoriser la stratification.

---

## 3. Mode logement collectif

### 3.1 Besoins ECS à 40 °C

Pour le logement neuf, HelioCOP utilise les coefficients d'équivalence en logements standards et les besoins journaliers à 40 °C fournis pour le projet :

- T1 : 0,6 / 75 L.eq40°C/j ;
- T2 : 0,7 / 80 L.eq40°C/j ;
- T3 : social 1,0 / 110 ; privé 0,9 / 100 ;
- T4 : social 1,4 / 145 ; privé 1,1 / 110 ;
- T5 : social 1,8 / 190 ; privé 1,3 / 140 ;
- T6+ : social 1,9 / 209 ; privé 1,4 / 140.

Les coefficients mensuels sont : 1,10 de janvier à mai, 0,85 en juin, 0,75 en juillet et août, 0,90 en septembre, 1,05 en octobre et 1,10 en novembre et décembre.

### 3.2 Eau froide

Trois méthodes sont disponibles :

- température fixée ;
- méthode ESM2 ;
- méthode ESM2 + 3 °C.

### 3.3 Stockage logement

Pour chaque mois :

`Vstock,40 = 0,80 × VECS,40`

puis :

`Vstock,60 = Vstock,40 × (40 - Tef) / (60 - Tef)`

Le volume cible est la moyenne annuelle des volumes journaliers équivalents à 60 °C, pondérée par le nombre de jours de chaque mois.

Les volumes unitaires disponibles sont 1 000, 1 250, 1 500, 2 000, 2 500 et 3 000 L. Les banques proposées dans cette version sont deux ballons identiques : 2 000, 2 500, 3 000, 4 000, 5 000 et 6 000 L.

### 3.4 Puissance ECS, bouclage et PAC

Source de `PECS` : COSTIC 2019, §2.3.2, figure 63.

`PECS = a × V^b`

avec :

`a = 14 × Ns + 495`

`b = -0,77 + 0,076 × ln(Ns)`

et `V` le volume réel de stockage retenu en litres.

Pour le schéma ECS2, le livret SOCOL adapte ensuite la méthode COSTIC afin de prendre en compte le bouclage :

`PDIM = PECS + PBoucl`

et :

`PnominalePAC = 0,70 × PECS + PBoucl`

Dans HelioCOP, `PBoucl` est estimée par la **plus forte puissance moyenne mensuelle** issue du calcul de bouclage de l'onglet 5 :

`PBoucl = max(Qboucl,m / (jours_m × 24))`

Cette approximation est adaptée à une note d'opportunité et reste à vérifier dans l'étude détaillée.

### 3.5 Appoint ECS2

Le livret SOCOL précise que l'appoint doit pouvoir assurer 100 % des besoins ECS en secours.

Pour climat océanique / méditerranéen ou faible risque de neige :

`Pappoint + PPAC,Textbase > 1,2 × (PECS + PBoucl)`

Pour climat continental ou fort risque de neige :

`Pappoint > 1,2 × (PECS + PBoucl)`

Cette vérification n'est pas encore automatisée dans HelioCOP V1.5.

---

## 4. Mode profil horaire / station de lavage poids lourds

Le livret SOCOL indique explicitement que les PAC solaires peuvent également être utilisées dans le secteur industriel ou agricole pour des applications avec préchauffage jusqu'à environ 60 °C, notamment **l'eau de lavage**.

Le cas industriel n'est cependant pas traité par un abaque standardisé ECS2. HelioCOP utilise donc directement le profil thermique réel lorsqu'il est disponible.

### 4.1 Format du profil

Le module accepte un fichier `.xlsx` ou `.csv` contenant exactement **8760 pas horaires**.

Le format HelioStock transmis est reconnu nativement :

- feuille : `besoins_8760h` ;
- colonnes calendaires : `month`, `day`, `hour` ;
- énergie thermique : `E besoin HT kWh` + `E besoin BT kWh`.

Si les colonnes calendaires sont absentes, HelioCOP reconstruit un calendrier non bissextile de 8760 h.

Le profil exemple `profil_8760h_Cholet2_pessimiste.xlsx` contient environ 144,75 MWh/an et une pointe moyenne horaire d'environ 148,84 kW.

### 4.2 Principe de calcul horaire

Aucun équivalent en logements standards et aucun abaque COSTIC n'est utilisé.

Pour chaque heure, HelioCOP connaît directement le besoin thermique `Qbesoin,h`. Le stockage ECS2 est représenté par un volume agrégé d'eau chaude à 60 °C. La Tef du mois permet de convertir énergie et volume :

`e_litre = 1,163 × (60 - Tef) / 1000` en kWh/L.

Le bilan horaire est :

`Stock(t+1) = Stock(t) + ProductionPAC(t) - Besoin(t)`

avec :

`0 ≤ Stock ≤ Volume_total`.

Le stockage est initialisé chargé à 100 %. Pour chaque couple PAC / stockage sont calculés :

- taux de couverture du profil ;
- énergie non couverte ;
- nombre d'heures non couvertes ;
- état de charge minimal ;
- heures équivalentes pleine charge.

### 4.3 Recherche des couples PAC / stockage

Toutes les banques ECS2 sont testées :

- 2 × 1 000 L ;
- 2 × 1 250 L ;
- 2 × 1 500 L ;
- 2 × 2 000 L ;
- 2 × 2 500 L ;
- 2 × 3 000 L.

Toutes les configurations PAC ECS de la bibliothèque sont testées avec jusqu'à **3 machines identiques**. Le moteur ne mélange ni modèles ni marques.

Pour chaque puissance PAC, HelioCOP conserve le plus petit stockage couvrant 100 % du profil, puis affiche le **front de Pareto puissance PAC / volume de stockage**.

### 4.4 Limites du moteur horaire V1.5

Le calcul ne représente pas encore :

- les deux niveaux thermiques réels « zone prioritaire / zone préchauffage » ;
- la stratification nodale ;
- les pertes thermiques des ballons et réseaux ;
- les marches/arrêts et temps minimum de fonctionnement ;
- la modulation de puissance ;
- la matrice complète de puissance/COP selon températures évaporateur et condenseur ;
- la disponibilité horaire de la source solaire ;
- la régulation des vannes V1/V2 ECS2 ;
- l'appoint dynamique.

Ces éléments sont réservés au futur moteur dynamique.

---

## 5. Données PAC issues de SoloPAC 1.1

Les fichiers XML SoloPAC fournis sont intégrés comme **références techniques** pour :

- HelioPAC Solerpac 8, 10, 12 et 14 kW ;
- Giordano SolarPump SPC20, SPC30 et SPC50.

Chaque XML contient notamment :

- COP EN14511 disponibles à B10/W45, B10/W55 et/ou B10/W65 selon le modèle ;
- puissance électrique absorbée aux mêmes points ;
- température minimale et maximale évaporateur ;
- température maximale condenseur ;
- débits nominaux évaporateur / condenseur ;
- puissances des circulateurs.

SoloPAC construit une matrice de performances à partir de ces points et de formules d'interpolation/extrapolation issues de la RE2020. **HelioCOP V1.5 ne reproduit pas ces formules.**

Pour information uniquement, l'interface affiche un repère B10/W60 lorsqu'il peut être interpolé entre des points valides et lorsque 60 °C reste dans la plage de fonctionnement déclarée. Cette valeur n'est pas présentée comme un résultat SoloPAC. Aucun repère à 60 °C n'est extrapolé pour la Solerpac P50, limitée à 55 °C côté chauffage dans la FT1p V3.1.

La Solerpac P25 reste une option de prédimensionnement HelioCOP mais aucun fichier de caractéristiques SoloPAC 1.1 n'est fourni pour ce modèle dans l'archive analysée.

La Solerpac P50 R407C est intégrée pour les usages **Process**, **Chauffage** et **Bassin**. La fiche technique HelioPAC FT1p V3.1 indique toutefois une température maximale côté chauffage de 55 °C : un usage visant réellement 60 °C doit être validé avec le fabricant ou avec une architecture adaptée.

---

## 6. Source solaire

### 6.1 Ratios de surface

REX fabricants transmis et valeurs de travail HelioCOP :

- moquette solaire : `5 m²/kW PAC installé` ;
- PVT : `4,5 m²/kW PAC installé`.

Ces valeurs sont cohérentes avec les plages indicatives du livret SOCOL ECS2 :

- capteurs non vitrés : **4 à 6 m²/kW PAC** ;
- PVT : **3 à 6 m²/kW PAC**.

L'interface permet désormais de modifier le ratio dans ces plages.

### 6.2 Références capteurs SoloPAC

L'archive SoloPAC 1.1 contient notamment :

- HelioPAC Solerpool : 2,50 m² par capteur ;
- Giordano Capteur4N : 4,70 m² par capteur ;
- Dualsun DSTI 425-108 : 1,95 m² ;
- Dualsun DSTN 425-108 : 1,95 m².

Pour une source non vitrée et une PAC HelioPAC/Giordano, HelioCOP propose un **arrondi du nombre de capteurs** à partir de la référence de même fabricant présente dans SoloPAC.

Les coefficients WISC (`eta0`, `a1` à `a8`, IAM, capacité thermique) sont conservés dans les XML pour une future modélisation dynamique de la source.

---

## 7. Bilan énergétique simplifié et indicateurs SOCOL

Le COP machine annuel reste un paramètre simplifié, fixé par défaut à 3,2.

`Ecompresseur = QPAC / COPmachine`

Lorsque les données SoloPAC sont disponibles, HelioCOP ajoute une estimation des consommations des circulateurs évaporateur et condenseur à partir de leurs puissances XML et des heures équivalentes pleine charge.

`WPACSolaire = Ecompresseur + Eauxiliaires`

`QEnR = QPAC - WPACSolaire`

Les trois indicateurs ECS2 du livret SOCOL sont également calculés :

`FSAV = 1 - (WPACSolaire + Qappoint) / (QPACSolaire + Qappoint)`

`COPmoyen = QPACSolaire / WPACSolaire`

`FPAC = QPACSolaire / (QPACSolaire + Qappoint)`

Dans cette V1.5, l'onglet économique suppose encore `Qappoint = 0` lorsque la solution est considérée comme couvrant le besoin ; le futur modèle dynamique devra calculer réellement l'appoint.

Le contrôle sur l'exemple `ECS2_Nantes` fourni avec SoloPAC reproduit bien les ordres de grandeur publiés dans son rapport : environ **FSAV 0,65**, **COP 3,02** et **FPAC 0,97**.

---

## 8. Aide indicative

Valeur par défaut :

`Aide = 600 € × MWh EnR`

La valeur reste modifiable dans l'interface.

## 9. Tendance de coût

Source : onglet `Evaluation cout` du fichier `NO PAC solaire_v2.xlsx` transmis.

`CAPEX = 43 854 + 2 362 × Ppac_installée + 300 × Ssource`

Une incertitude de ±20 % est affichée par défaut. Cette relation reste un ordre de grandeur de note d'opportunité et ne remplace pas une estimation projet détaillée.

## COP mensuels PAC solaire à 60 °C — V1.5

Le bilan énergétique simplifié n'utilise plus un COP annuel unique. HelioCOP applique aux besoins thermiques adressés de chaque mois les COP de référence suivants pour une production à 60 °C :

| Mois | COP |
|---|---:|
| Janvier | 2,53236 |
| Février | 2,89346 |
| Mars | 3,17380 |
| Avril | 3,30696 |
| Mai | 3,15356 |
| Juin | 3,45954 |
| Juillet | 3,68322 |
| Août | 3,68457 |
| Septembre | 3,42448 |
| Octobre | 3,09132 |
| Novembre | 3,07363 |
| Décembre | 2,94027 |

Pour chaque mois :

```text
E_comp,m = Q_PAC,m / COP_m
```

Le COP PAC saisonnier est ensuite recalculé par pondération énergétique :

```text
COP_saisonnier = somme(Q_PAC,m) / somme(E_comp,m)
```

Les auxiliaires hydrauliques issus des fichiers SoloPAC, lorsqu'ils sont disponibles, sont ajoutés séparément au dénominateur du COP système.

## Coût de chaleur PAC solaire P1 / P2 / P4

La V1.5 reprend la logique économique HelioEco pour transformer le bilan énergétique et les REX d'investissement en coût de chaleur.

### P1 — énergie électrique

```text
P1_annuel = (E_compresseur + E_auxiliaires) * prix_electricite
P1 = P1_annuel / Q_PAC
```

### P2 — suivi et maintenance

Pour la PAC solaire, HelioCOP retient un forfait de maintenance indépendant de la taille de l'installation :

```text
P2_PAC_annuel = 2 000 € HT/an
```

Si le contexte est « chaudière gaz à renouveler », le scénario PAC solaire inclut également la maintenance de sa chaudière gaz d'appoint / secours :

```text
P2_scenario_PAC = 2 000 + P_chaudiere_PAC * cout_maintenance_chaudiere
P2 = P2_scenario_PAC / Q_PAC
```

### P4 — investissement net aidé

Comme dans HelioEco, le calcul simplifié n'utilise pas encore de facteur d'actualisation. En contexte chaudière à renouveler, la chaudière gaz est comptée dans **les deux scénarios** :

```text
Investissement_reference = CAPEX_chaudiere_reference
Investissement_scenario_PAC = CAPEX_PAC_solaire - aide + CAPEX_chaudiere_appoint
P4_PAC = Investissement_scenario_PAC / (Q_PAC * duree_analyse)
P4_reference = Investissement_reference / (Q_reference * duree_analyse)
```

Le surinvestissement initial pertinent est alors :

```text
Surinvestissement_net = Investissement_scenario_PAC - Investissement_reference
```

### Coût de chaleur

```text
Cout_chaleur = P1 + P2 + P4
```

Le CAPEX reste basé sur les REX transmis :

```text
CAPEX = 43 854 + 2 362 * P_PAC_installee + 300 * Surface_source
```

Cette loi n'isole pas encore explicitement le coût des ballons de stockage. Les comparaisons de solutions Pareto à volumes très différents doivent donc être interprétées comme des ordres de grandeur de note d'opportunité.


## V1.5.4 — clarification des scénarios d'investissement

En contexte « chaudière gaz à renouveler », HelioCOP distingue désormais explicitement :

- **Scénario 1 — Référence gaz** : chaudière gaz 100 % besoins, sans PAC solaire ;
- **Scénario 2 — PAC solaire + gaz** : investissement PAC solaire + chaudière gaz d'appoint / secours.

Les puissances de chaudière peuvent être saisies séparément pour les deux scénarios. Par défaut elles sont identiques. Les coûts unitaires chaudière (CAPEX en €/kW et maintenance en €/kW.an) sont appliqués à chaque scénario.

L'aide est appliquée uniquement au CAPEX PAC solaire. L'incertitude CAPEX ±X % porte uniquement sur la loi REX PAC solaire et n'affecte pas le coût de chaudière gaz. Le P4 du scénario PAC inclut toutefois la chaudière gaz lorsque celle-ci doit être renouvelée.


## V1.6 — import des résultats mensuels SOLOPAC

HelioCOP peut importer un export mensuel SOLOPAC et ne conserve que les colonnes utiles : `BECS`, `QPAC_Evap`, `QPAC_Cond`, `PAbs_PAC`, `Waux`, `QChaudiere` et `COP`.

Le bilan technique utilise :

```text
Q_EnR = QPAC_Evap
E_elec = PAbs_PAC + Waux
Q_appoint_gaz = QChaudiere
COP_systeme = QPAC_Cond / (PAbs_PAC + Waux)
Taux_EnR = QPAC_Evap / (QPAC_Cond + QChaudiere)
Couverture_PAC = QPAC_Cond / (QPAC_Cond + QChaudiere)
```

Pour l'économie actualisée, le P1 du scénario PAC solaire intègre désormais les consommations réellement simulées :

```text
P1_annuel = (PAbs_PAC + Waux) * prix_electricite
           + (QChaudiere / rendement_chaudiere) * prix_gaz
```

Les P2/P4, CAPEX REX, aide et comparaison avec la référence gaz restent fondés sur les hypothèses économiques saisies dans l'onglet 7. L'aide est calculée sur `QPAC_Evap`, c'est-à-dire l'énergie renouvelable captée à l'évaporateur.
