# Notice technique du modèle HelioStock horaire

Cette notice décrit les équations et hypothèses effectivement codées dans la version actuelle du module.

Environnement numérique recommandé : Python 3.11 ou 3.12 avec les dépendances bornées dans `requirements.txt`.
Les versions plus récentes non qualifiées, notamment Python 3.14, peuvent provoquer des comportements différents dans
Streamlit, pandas, scipy ou pygfunction.

Le modèle actif dans l’interface Streamlit est le modèle horaire `simulate_hourly(...)`. L’ancien moteur de résolution mensuelle a été supprimé : les tableaux mensuels affichés sont uniquement des agrégations des résultats horaires.

Le calcul principal reste une année 8760 h. Une projection physique multiannuelle répète ensuite la même année météo et
les mêmes besoins horaires sur 25 ans par défaut. L'état thermique du champ de sondes est
conservé d'une année à l'autre afin de visualiser la recharge ou l'épuisement progressif du sous-sol. La projection est
calculée pour la géothermie seule et pour la géothermie avec recharge solaire, avec le modèle champ de sondes
`pygfunction`.

Le P1 électrique PAC/géothermie distingue l'électricité compresseur de l'électricité complète PAC. Un forfait prudent
de pré-dimensionnement ajoute 15 % d'auxiliaires PAC/géothermie et 0,05 kW de veille/régulation. Les pompes solaires et
les pompes de transfert solaire vers BTES ne sont pas ajoutées dans cette version ; le `P1'` auxiliaires solaires
historique reste disponible pour le solaire thermique.

## 1. Périmètre physique modélisé

Le système représenté est :

```text
EPW météo horaire
    -> champ de capteurs solaires thermiques
    -> ballon solaire journalier
    -> préchauffage du process HT air extérieur -> 60 °C
    -> appoint HT pour le complément

surplus solaire disponible
    -> injection dans champ de sondes BTES
    -> PAC géothermique
    -> process BT air extérieur -> 25 °C
```

Les deux besoins process sont actuellement saisis en `kWh/mois`, puis répartis uniformément sur les heures du mois. Ce n’est donc pas encore un vrai profil horaire industriel 8760 h.

## 2. Unités principales

| Grandeur | Unité dans le code |
|---|---:|
| Énergie | kWh |
| Puissance horaire affichée | kW, car un pas vaut 1 h donc `kWh/h = kW` |
| Température | °C |
| Irradiation horaire plan capteur | kWh/m² sur l’heure |
| Irradiance moyenne `G` | W/m² |
| Surface capteurs | m² |
| Volume ballon | L |
| Capacité thermique eau | `1,163e-3 kWh/L.K` |

## 3. Lecture météo EPW

Fichier concerné : `heliostock/epw_reader.py`.

Le lecteur EPW extrait notamment :

- température extérieure sèche : colonne EPW `dry bulb`, utilisée comme `Tair` ;
- GHI : rayonnement global horizontal, Wh/m² ;
- DNI : rayonnement direct normal, Wh/m² ;
- DHI : rayonnement diffus horizontal, Wh/m² ;
- localisation : latitude, longitude, fuseau horaire, altitude.

### 3.1 Géométrie solaire

L’heure EPW est codée de 1 à 24. Le calcul utilise le milieu de l’heure :

```text
hour_local = hour_epw - 0,5
```

Le jour de l’année est noté `n`.

Équation du temps :

```text
B = 360 * (n - 81) / 364
EoT = 9,87 * sin(2B) - 7,53 * cos(B) - 1,5 * sin(B)
```

avec `B` en radians dans le calcul.

Temps solaire :

```text
longitude_standard = 15 * timezone
solar_time = hour_local + (4 * (longitude_standard - longitude) + EoT) / 60
```

Angle horaire :

```text
omega = 15 * (solar_time - 12)
```

Déclinaison solaire :

```text
delta = 23,45 * sin(360 * (284 + n) / 365)
```

Cosinus de l’angle zénithal :

```text
cos(theta_z) =
    sin(latitude) * sin(delta)
  + cos(latitude) * cos(delta) * cos(omega)
```

Cosinus d’incidence sur le plan capteur :

```text
cos(theta_i) =
    sin(delta) * sin(latitude) * cos(beta)
  - sin(delta) * cos(latitude) * sin(beta) * cos(gamma)
  + cos(delta) * cos(latitude) * cos(beta) * cos(omega)
  + cos(delta) * sin(latitude) * sin(beta) * cos(gamma) * cos(omega)
  + cos(delta) * sin(beta) * sin(gamma) * sin(omega)
```

avec :

- `beta` = inclinaison des capteurs ;
- `gamma` = azimut par rapport au sud, `0 = sud`, `-90 = est`, `+90 = ouest`.

### 3.2 Transposition du rayonnement sur le plan capteur

Le modèle utilise une transposition simple :

```text
beam = DNI * max(0, cos(theta_i)) si cos(theta_z) > 0
beam = 0 sinon
```

Diffus isotrope :

```text
diffuse = DHI * (1 + cos(beta)) / 2
```

Réfléchi par le sol :

```text
reflected = GHI * albedo * (1 - cos(beta)) / 2
```

Irradiation horaire dans le plan capteur :

```text
G_tilt_h = max(0, beam + diffuse + reflected) / 1000
```

`G_tilt_h` est en `kWh/m²` sur l’heure.

Hypothèses associées :

- pas de modèle circumsolaire détaillé ;
- pas de masque proche ou lointain ;
- pas d’horizon réel ;
- pas de IAM capteur ;
- pas de pertes neige/salissure explicites ;
- l’albédo est constant.

## 4. Import des besoins horaires 8760 h

Fichier concerné : `heliostock/load_profiles.py`, fonction `_hourly_demands_from_process_file(...)`.

Le moteur physique exige un profil horaire explicite transmis via `hourly_demand_override`. L'interface ne lance pas le
calcul sans fichier Excel process valide.

Format attendu dans la première feuille :

```text
Date heure
P besoin HT kW ou E besoin HT kWh
P besoin BT kW ou E besoin BT kWh
```

Mapping retenu :

```text
Besoin HT -> process 60 °C
Besoin BT -> process 25 °C
```

Les valeurs horaires sont utilisées directement :

```text
Q_HT_h = valeur horaire besoin HT
Q_BT_h = valeur horaire besoin BT
```

Les agrégats mensuels encore présents dans certaines signatures servent uniquement de résumé de profil ou de compatibilité
interne. Ils ne remplacent pas le profil horaire dans les tests ni dans le flux Streamlit.

## 5. Rendement des capteurs solaires thermiques

Fichiers concernés :

- `heliostock/engine.py`, fonction `collector_efficiency(...)` ;
- `heliostock/hourly_engine.py`, fonction `_solar_yield_hour_kwh(...)`.

Le rendement instantané est de type EN12975 simplifié :

```text
eta = eta0
    - a1 * (T_mean - T_air) / G
    - a2 * (T_mean - T_air)^2 / G
```

avec :

- `eta0` : rendement optique ;
- `a1` : coefficient de pertes linéaires, W/m².K ;
- `a2` : coefficient de pertes quadratiques, W/m².K² ;
- `T_mean` : température moyenne capteur, °C ;
- `T_air` : température extérieure horaire, °C ;
- `G` : irradiance moyenne horaire dans le plan capteur, W/m².

Dans le code horaire :

```text
G = G_tilt_h * 1000
```

car `G_tilt_h` est une irradiation sur 1 h en kWh/m², numériquement équivalente à une puissance moyenne en kW/m².

Cas de nuit :

```text
si G <= 0 ou G_tilt_h <= 0 :
    eta = 0
    production solaire = 0
```

Le rendement est ensuite borné :

```text
eta = max(0, min(eta, eta0))
```

Le code force aussi :

```text
deltaT = max(0, T_mean - T_air)
```

Donc si le capteur est plus froid que l’air, il ne génère pas un rendement supérieur à `eta0`.

## 6. Production solaire horaire

Pour une température moyenne capteur donnée :

```text
Q_solaire_h = G_tilt_h * A_capteurs * eta * eta_systeme
```

avec :

- `G_tilt_h` en kWh/m² ;
- `A_capteurs` en m² ;
- `eta` rendement capteur ;
- `eta_systeme` rendement hydraulique global.

Dans le code :

```text
eta_systeme = max(0, min(1, system_efficiency))
```

La production est bornée à zéro :

```text
Q_solaire_h = max(0, Q_solaire_h)
```

## 7. Température capteur pour charger le ballon solaire

Le solaire thermique ne va pas directement au process HT. Il charge d’abord le ballon journalier.

Température moyenne capteur utilisée pour la charge ballon :

```text
T_capteur_ballon =
    max(
        T_ambiance_ballon + approche_capteur_ballon,
        T_ballon_debut_heure + approche_capteur_ballon
    )
```

Comme `T_ballon_debut_heure >= T_ambiance_ballon`, cela revient en pratique à :

```text
T_capteur_ballon ~= T_ballon_debut_heure + approche_capteur_ballon
```

Valeur par défaut :

```text
approche_capteur_ballon = 10 K
```

Cette température sert uniquement au calcul du rendement capteur de charge ballon.

## 8. Modèle du ballon solaire journalier

Fichier concerné : `heliostock/hourly_engine.py`.

Le ballon est modélisé comme un volume d’eau équivalent.

Volume :

```text
V_ballon = A_capteurs * volume_ballon_L_par_m2
```

Capacité thermique :

```text
C_ballon = V_ballon * 1,163e-3
```

avec `C_ballon` en kWh/K.

Énergie stockée au-dessus de l’ambiance :

```text
E_buffer = C_ballon * (T_ballon - T_ambiance_ballon)
```

Température du ballon :

```text
T_ballon = T_ambiance_ballon + E_buffer / C_ballon
```

Capacité maximale physique, utilisée comme borne de sécurité :

```text
E_buffer_max = C_ballon * (Tmax_ballon - T_ambiance_ballon)
```

Valeurs par défaut :

```text
T_ambiance_ballon = 20 °C
Tmax_ballon = 80 °C
volume_ballon = 50 L/m² capteur
```

## 9. Bascule vers BTES à Tmax ballon

Le ballon est prioritaire. Le BTES n’est chargé que lorsque le ballon ne peut plus absorber toute la ressource solaire disponible, donc lorsque sa capacité restante jusqu’à `Tmax_ballon` est nulle.

```text
Tmax_ballon = 80 °C par défaut
```

Énergie équivalente à `Tmax_ballon` :

```text
E_buffer_max = C_ballon * (Tmax_ballon - T_ambiance_ballon)
```

À chaque heure :

```text
capacite_restante_ballon = max(0, E_buffer_max - E_buffer)
```

La charge solaire du ballon vaut :

```text
Q_solaire_vers_ballon =
    min(
        Q_solaire_potentiel_ballon * facteur_charge_ballon,
        capacite_restante_ballon
    )
```

La fraction de ressource solaire restante est donc nulle tant que le ballon peut absorber toute la production solaire de l'heure. Elle devient positive quand le ballon est à `Tmax_ballon` ou proche de cette limite.

Le surplus de ressource solaire non utilisé pour charger le ballon peut ensuite être recalculé à température plus basse pour l’injection BTES.

Si `facteur_charge_ballon < 1`, la part non chargée à cause de ce facteur n'est pas automatiquement envoyée vers le BTES. Dans cette version, le BTES reste autorisé uniquement lorsque la limite `Tmax_ballon` est atteinte.

Point important : le code ne modélise pas une vanne hydraulique détaillée. Il représente l’effet de régulation par une priorité énergétique : ballon jusqu’à `Tmax_ballon`, puis BTES.

L'énergie réellement stockée dans le ballon peut ensuite redescendre sous `Tmax_ballon` pendant la même heure, car les pertes ballon et le préchauffage HT sont appliqués après la charge solaire.

Ancienne logique supprimée : il n’y a plus de seuil séparé à 65 °C.

## 10. Pertes du ballon solaire

Les pertes du ballon solaire ne sont plus calculées avec une fraction fixe de l'énergie stockée par jour.
Le code utilise une constante de refroidissement de type SOLO2018, calculée à partir du volume de ballon, du
nombre de ballons, de l'épaisseur d'isolant, du lambda isolant et de la surface équivalente du ballon.

La constante obtenue est :

```text
CRStockSolaire [Wh/L/K/jour]
```

La perte journalière SOLO2018 est :

```text
Q_pertes_ballon_jour =
    (T_ballon - T_ambiance_ballon)
    * V_ballon_litres
    * CRStockSolaire
    / 1000
```

Comme HelioStock fonctionne au pas horaire, le code applique :

```text
Q_pertes_ballon_h =
    (T_ballon - T_ambiance_ballon)
    * V_ballon_litres
    * CRStockSolaire
    / 1000
    / 24
```

Le code borne toujours la perte pour ne pas extraire plus que l'énergie disponible :

```text
Q_pertes_ballon_h = min(E_buffer, Q_pertes_ballon_h)
```

Hypothèse : le ballon reste représenté par une température unique. Il ne s'agit pas d'un modèle stratifié.

## 11. Préchauffage HT par le ballon solaire

Le process HT cible :

```text
T_process_HT = 60 °C par défaut
```

Le ballon peut préchauffer l’air jusqu’à une température dépendant de son niveau thermique :

```text
T_sortie_prechauffage =
    min(
        T_process_HT,
        T_cible_max_prechauffage_solaire,
        max(T_air, T_ballon - approche_echangeur_ballon_process)
    )
```

Valeurs par défaut :

```text
T_cible_max_prechauffage_solaire = 60 °C
approche_echangeur_ballon_process = 5 K
```

Le préchauffage solaire peut donc couvrir :

- 0 % si le ballon est trop froid ;
- une fraction partielle si le ballon permet par exemple 25, 30 ou 40 °C ;
- 100 % si le ballon permet d’atteindre 60 °C.

La fraction du besoin HT couverte par le préchauffage est calculée par ratio de relèvement de température :

```text
deltaT_total_HT = max(0, T_process_HT - T_air)
deltaT_solaire_HT = max(0, T_sortie_prechauffage - T_air)

fraction_prechauffage =
    min(1, deltaT_solaire_HT / deltaT_total_HT)
```

Si `deltaT_total_HT = 0`, la fraction vaut `0`.

Énergie HT théoriquement préchauffable par le ballon :

```text
Q_HT_prechauffable = Q_HT_besoin_h * fraction_prechauffage
```

Énergie réellement prise au ballon :

```text
Q_HT_solaire = min(Q_HT_prechauffable, E_buffer)
```

Puis :

```text
E_buffer = E_buffer - Q_HT_solaire
```

Appoint HT :

```text
Q_appoint_HT = max(0, Q_HT_besoin_h - Q_HT_solaire)
```

Variable historique à connaître :

- dans `HourlyResult`, le champ principal est `solar_ht_from_buffer_kwh` : il contient le préchauffage HT solaire via ballon ;
- le champ `solar_ht_direct_kwh` reste seulement un alias de compatibilité pour les exports historiques ;
- aucun de ces champs ne représente un solaire direct capteurs -> process.

## 12. Fraction de ressource solaire restante pour BTES

Le code calcule d’abord le potentiel solaire à température de charge ballon :

```text
Q_solaire_potentiel_ballon
```

Puis la fraction utilisée pour charger le ballon :

```text
fraction_utilisee_ballon =
    Q_solaire_vers_ballon / Q_solaire_potentiel_ballon
```

si `Q_solaire_potentiel_ballon > 0`, sinon `0`.

La fraction restante vaut :

```text
fraction_restante = max(0, 1 - fraction_utilisee_ballon)
```

Cette fraction restante est ensuite appliquée à un nouveau calcul solaire, cette fois à la température d’injection BTES.

Hypothèse importante : ce n’est pas une simulation hydraulique multi-circuits détaillée. C’est une allocation énergétique simplifiée de la ressource solaire horaire.

## 13. Température capteur pour injection BTES

Le niveau de température capteur pour le stockage BTES dépend de la température du champ au début de l’heure :

```text
T_capteur_BTES =
    min(
        T_capteur_stockage_max,
        max(T_capteur_stockage_min, T_champ_debut + marge_injection_BTES)
    )
```

Valeurs par défaut :

```text
T_capteur_stockage_min = 25 °C
T_capteur_stockage_max = 45 °C
marge_injection_BTES = 5 K
```

Le rendement capteur est recalculé avec cette température.

Production solaire brute à température BTES :

```text
Q_solaire_BTES_brut =
    G_tilt_h * A_capteurs * eta_BTES * eta_systeme
```

Potentiel affecté au BTES :

```text
Q_solaire_BTES_potentiel =
    Q_solaire_BTES_brut * fraction_restante
```

## 14. Modèle BTES / champ de sondes expert pygfunction

HelioStock utilise désormais un seul backend actif pour le champ de sondes : `pygfunction`.

Si `pygfunction` n'est pas installé, l'application échoue explicitement avec le message d'installation.

Convention de signe et d'unité :

```text
extraction PAC depuis le sol : positive
injection solaire dans le sol : négative
q_net_W_m = q_extraction_W_m - q_injection_W_m
q_W_m = Q_kWh * 1000 / longueur_totale_sondes_m
```

La chaleur envoyée au champ n'est pas la chaleur utile BT livrée au process. Pour la PAC :

```text
Q_BT_livree = chaleur utile process BT
Electricite_compresseur = Q_BT_livree / COP
Q_sol_extrait = Q_BT_livree - Electricite_compresseur
```

Le COP dépend de la température fluide source PAC :

```text
COP = eta_carnot * T_cond,K / (T_cond,K - T_evap,K)
T_cond_C = T_cible_BT + approche_condenseur
T_evap_C = T_source_PAC - approche_evaporateur
T_source_PAC ~= T_paroi_forage - q_extraction_W_m * Rb_eff
```

Cette correction `q * Rb_eff` est une approximation V1. Elle distingue la température de paroi forage calculée par
`pygfunction` et la température fluide source utilisée pour la PAC. Elle ne doit pas être appliquée deux fois si un
modèle hydraulique détaillé de sonde est ajouté plus tard.

Les limitations actives sont :

- puissance PAC installée ;
- puissance linéique maximale d'extraction/injection ;
- température source minimale PAC ;
- température maximale d'injection/champ ;
- bornes COP min/max.

Limites restantes : ce n'est pas encore un dimensionnement réglementaire. La géométrie automatique est approximative et
doit être remplacée par une géométrie réelle en étude détaillée. Les résultats doivent être vérifiés par un BET
géothermie ou un outil spécialisé avant engagement.

## 15. Injection solaire dans le BTES

L'injection solaire est convertie en charge linéique sur la longueur totale de sondes :

```text
L_total_sondes_m = nombre_sondes * profondeur_sonde
q_injection_W_m = Q_injection_BTES_kWh * 1000 / L_total_sondes_m
```

La chaleur injectée est limitée par trois contraintes actives :

- le potentiel solaire affecté au BTES après priorité au ballon ;
- la puissance linéique maximale d'injection ;
- la température de paroi maximale autorisée, via la résistance thermique de forage.

Dans le moteur :

```text
Q_injection_BTES = min(
    Q_solaire_BTES_potentiel * rendement_injection,
    max_injection_W_m * L_total_sondes_m / 1000,
    max(0, (Tmax_champ - T_paroi_debut) / Rb_eff) * L_total_sondes_m / 1000
)
```

Le flux non injecté reste non valorisé :

```text
Q_solaire_non_valorise =
    max(0, Q_solaire_BTES_potentiel - Q_injection_BTES)
    max(0, Q_solaire_BTES_potentiel - Q_injection_BTES)
```

## 16. COP de la PAC géothermique

Fichier concerné : `heliostock/engine.py`, fonction `cop_from_source_temperature(...)`.

La PAC couvre le besoin basse température `air extérieur -> 25 °C`.

Température de condensation approchée :

```text
T_cond_K = T_cible_BT + approche_condenseur + 273,15
```

Température d’évaporation approchée :

```text
T_source_PAC = T_paroi_forage - q_extraction_W_m * Rb_eff
T_evap_K = T_source_PAC - approche_evaporateur + 273,15
```

COP de Carnot :

```text
COP_Carnot = T_cond_K / (T_cond_K - T_evap_K)
```

COP réel :

```text
COP = rendement_Carnot_PAC * COP_Carnot
```

Puis bornage :

```text
COP = max(COP_min, min(COP_max, COP))
```

Valeurs par défaut :

```text
T_cible_BT = 25 °C
approche_condenseur = 2 K
approche_evaporateur = 3 K
rendement_Carnot_PAC = 0,45
COP_min = 2
COP_max = 8
```

Cas particuliers :

```text
si T_evap_K <= 0 :
    COP = COP_min

si T_evap_K >= T_cond_K :
    COP = COP_max
```

## 17. Couverture du besoin BT par PAC

Besoin horaire :

```text
Q_BT_besoin_h
```

La chaleur livrée par PAC est d'abord limitée par la puissance PAC installée :

```text
Q_BT_PAC_cible = min(Q_BT_besoin_h, P_PAC_installee)
```

Si `Q_BT_PAC_cible > 0` et `COP > 1`, alors la fraction de chaleur livrée par la PAC qui vient du champ est :

```text
fraction_champ = 1 - 1 / COP
```

La chaleur extraite du champ est bornée par la puissance linéique maximale et par la température source minimale :

```text
Q_sol_max_puissance = max_extraction_W_m * L_total_sondes_m / 1000
Q_sol_max_temperature = max(0, (T_paroi_debut - Tmin_champ) / Rb_eff) * L_total_sondes_m / 1000
Q_sol_max = min(Q_sol_max_puissance, Q_sol_max_temperature)
```

Chaleur BT maximale livrable par la PAC compte tenu de ces limites :

```text
Q_BT_max_PAC = Q_sol_max / fraction_champ
```

Chaleur BT réellement livrée :

```text
Q_BT_PAC = min(Q_BT_PAC_cible, Q_BT_max_PAC)
```

Électricité PAC :

```text
W_PAC = Q_BT_PAC / COP
```

Chaleur extraite du champ :

```text
Q_extrait_champ = Q_BT_PAC - W_PAC
```

La charge nette envoyée à `pygfunction` est ensuite :

```text
q_net_W_m = q_extraction_W_m - q_injection_W_m
```

Appoint BT :

```text
Q_appoint_BT = max(0, Q_BT_besoin_h - Q_BT_PAC)
```

## 19. Ordre exact de calcul sur une heure

Pour chaque heure EPW, le moteur fait exactement :

1. Lecture des besoins horaires HT et BT du profil 8760 h.
2. Lecture de l'état thermique `pygfunction` au début de l'heure.
3. Calcul de `T_ballon_debut`.
4. Calcul de `T_capteur_ballon`.
5. Calcul du potentiel solaire à température ballon.
6. Charge du ballon jusqu’à `Tmax_ballon`.
7. Application des pertes horaires du ballon.
8. Calcul de la température de préchauffage HT possible.
9. Décharge du ballon vers le préchauffage HT.
10. Calcul de l’appoint HT.
11. Calcul de la fraction de ressource solaire restante.
12. Calcul de `T_capteur_BTES`.
13. Calcul du potentiel solaire à température BTES.
14. Injection dans le BTES.
15. Calcul du COP PAC avec la température source estimée.
16. Couverture du besoin BT par PAC, limitée par la puissance PAC, la puissance linéique et la Tmin source PAC operationnelle.
17. Extraction BTES par la PAC.
18. Mise à jour `pygfunction` avec `q_net_W_m`.
19. Stockage de tous les résultats horaires.

## 20. Bilans énergétiques vérifiés par les tests

Les tests présents dans `test_engine_smoke.py` vérifient notamment :

### 20.1 Bilan ballon

Pour chaque heure :

```text
E_buffer_fin =
    E_buffer_debut
  + Q_solaire_vers_ballon
  - Q_prechauffage_HT_solaire
  - Q_pertes_ballon
```

### 20.2 Charge lineique BTES

Pour chaque heure :

```text
q_net_W_m = q_extraction_W_m - q_injection_W_m
q_extraction_W_m = Q_extrait_champ_PAC * 1000 / L_total_sondes_m
q_injection_W_m = Q_injection_BTES * 1000 / L_total_sondes_m
```

### 20.3 Bilan PAC

```text
Q_BT_PAC = Q_extrait_champ_PAC + W_PAC
```

### 20.4 Bilan HT

```text
Q_HT_besoin = Q_prechauffage_HT_solaire + Q_appoint_HT
```

### 20.5 Nuit

Si `G_tilt_h = 0` :

```text
eta_capteur = 0
production_solaire = 0
```

## 21. Grandeurs affichées dans l’interface

Les valeurs affichées dans `streamlit_module.py` sont toutes issues de la table horaire `hourly_df`.

Principales correspondances :

| Affichage | Colonne horaire |
|---|---|
| Besoin total | `demand_ht_kwh + demand_bt_kwh` |
| Préchauffage HT solaire | `solar_ht_from_buffer_kwh` |
| Charge ballon solaire | `solar_ht_to_buffer_kwh` |
| Injection BTES | `solar_to_btes_kwh` |
| T ballon max | max de `solar_ht_buffer_temp_end_c` |
| T ballon fin | dernière valeur de `solar_ht_buffer_temp_end_c` |
| Température source PAC | `T_source_PAC_C` |
| Température paroi forage | `T_paroi_forage_C` |
| Température évaporateur PAC | `T_evaporateur_PAC_C` |
| Puissance linéique nette champ | `q_net_W_m` |
| COP PAC moyen | somme `heat_bt_from_pac_kwh` / somme `electricity_compressor_kwh` |
| Monotone synchronisée | les heures sont triées selon une référence choisie, puis toutes les courbes sont affichées dans ce même ordre |
| Mix HT monotone | heures triées par `demand_ht_kwh`, aire empilée solaire thermique + appoint HT |
| Mix BT monotone | heures triées par `demand_bt_kwh`, aire empilée PAC géothermie + appoint BT |

Les tableaux mensuels affichés ne sont pas une méthode de calcul mensuelle. Ce sont uniquement des agrégations des 8760 résultats horaires.

Point important sur la monotone : les courbes ne sont plus triées indépendamment. Cela préserve la simultanéité horaire. Si le rang 1 correspond à l’heure de plus fort besoin HT, alors les valeurs solaire et PAC affichées au rang 1 sont celles de cette même heure réelle.

Les graphes de mix HT/BT sont empilés :

```text
Besoin HT = préchauffage solaire HT + appoint HT
Besoin BT = chaleur PAC géothermie + appoint BT
```

La partie EnR est placée en bas de l'aire, l'appoint en complément au-dessus.

### 21.1 Flux sous-sol affichés

Dans les graphes mensuels du sous-sol :

```text
injection solaire BTES > 0
extraction champ vers PAC < 0
bilan net sol = injection solaire - extraction PAC
```

## 22. Indicateurs économiques préparatoires

L'interface ajoute plusieurs indicateurs utiles pour la future analyse économique.

### 22.1 Productivité solaire valorisée

La productivité solaire valorisée rapporte uniquement l'énergie solaire utile à la surface de capteurs :

```text
productivite_solaire_valorisee =
    (Q_prechauffage_HT_solaire + Q_injection_BTES) / surface_capteurs
```

Unité :

```text
kWh/m².an
```

Le solaire chargé puis perdu dans le ballon, ou non valorisé, n'est pas compté dans cette productivité.

### 22.2 Consommation d'appoint

```text
Q_appoint_total = Q_appoint_HT + Q_appoint_BT
```

### 22.3 Taux de couverture solaire annuel du besoin HT

```text
taux_couverture_solaire_HT =
    Q_prechauffage_HT_solaire / Q_besoin_HT
```

Le numérateur est l'énergie réellement extraite du ballon vers le préchauffage HT.

### 22.4 Comparaison COP avec et sans solaire

Deux simulations horaires sont réalisées :

```text
cas avec solaire : surface capteurs saisie
cas sans solaire : surface capteurs = 0
```

Le COP annuel PAC est :

```text
COP_annuel = somme(Q_BT_PAC) / somme(W_PAC)
```

### 22.5 Économie équivalente de sondes à COP équivalent

Le cas de référence est le cas sans solaire avec le champ complet :

```text
COP_reference = COP_sans_solaire
Q_BT_reference = Q_BT_PAC_sans_solaire
```

Ensuite le modèle relance le cas avec solaire en réduisant progressivement le nombre de sondes.

Le critère de validation est :

```text
COP_avec_solaire_reduit >= COP_reference
Q_BT_PAC_avec_solaire_reduit >= Q_BT_reference
```

La recherche se fait par dichotomie.

La recherche modifie la géométrie simulée par `pygfunction` en diminuant le nombre de sondes, puis traduit le résultat
en longueur équivalente :

```text
L_reference = nombre_sondes * profondeur
L_equivalente = nombre_sondes_reduit * profondeur
L_economisee = L_reference - L_equivalente
taux_economie = L_economisee / L_reference
```

Interprétation importante : ce n'est pas encore un dimensionnement réglementaire de champ de sondes. C'est un
indicateur de potentiel d'économie de linéaire fondé sur le même moteur `pygfunction`, utile pour comparer des variantes
avant étude détaillée.

### 22.6 Taux EnR global du projet

La convention retenue est :

```text
appoint_HT = non EnR
appoint_BT = non EnR
electricite_PAC = non EnR
```

Le taux EnR global est calculé sur les besoins utiles HT + BT :

```text
taux_EnR_global =
    1 - (appoint_HT + appoint_BT + electricite_PAC) / (besoin_HT + besoin_BT)
```

Le résultat est borné entre 0 et 100 %.

Interprétation :

- le préchauffage solaire HT est compté EnR ;
- la chaleur extraite du champ par la PAC est comptée EnR ;
- l'électricité consommée par la PAC n'est pas comptée EnR ;
- les appoints ne sont pas comptés EnR.

## 23. Analyse économique solaire thermique

Fichier concerné : `heliostock/streamlit_module.py`.

Le périmètre économique ajouté est volontairement limité au solaire thermique. La géothermie n’est pas encore chiffrée
économiquement.

L’énergie solaire annuelle valorisée retenue est :

```text
Q_solaire_valorisee =
    Q_prechauffage_HT_solaire
  + Q_injection_BTES
```

Unités :

```text
Q_solaire_valorisee en MWh/an
surface S en m²
```

### 23.1 CAPEX solaire thermique

Le CAPEX brut est calculé par loi surfacique :

```text
CAPEX_brut = S * C_unitaire(S)
```

avec :

```text
si S <= 100 :
    C_unitaire = 1500

si 100 < S <= 1000 :
    C_unitaire = 1500 - 0,5556 * (S - 100)

si 1000 < S <= 1500 :
    C_unitaire = 1000 - 0,35 * (S - 1000)

si S > 1500 :
    C_unitaire = -159,1 * ln(S) + 1990,2
```

`C_unitaire` est en €/m².

### 23.2 Aide ADEME solaire

La formule fournie est implémentée avec le mapping suivant :

| Variable formule | Interprétation dans le code |
|---|---|
| `S` | surface capteurs, m² |
| `X9` | énergie solaire valorisée annuelle, MWh/an |
| `Hypothèses!D13` | aide énergie, €/MWh.an |
| `X17` | CAPEX brut solaire, € |
| `X19` | autres aides publiques déjà acquises, € |

Productivité annuelle :

```text
productivite = X9 / S
```

Facteur de lissage :

```text
f = min(1, exp((1500 - S) / 1500))
```

Coût unitaire grand projet :

```text
C_grand = -159,1 * ln(S) + 1990,2
```

Aide brute formule :

```text
aide_formule =
    min(S, 1500) * productivite * aide_energie * 20 * f
  + (max(S, 1500) - 1500 * f) * C_grand * 0,5
```

Plafond :

```text
aide_plafond = 0,65 * CAPEX_brut - autres_aides_publiques
```

Aide ADEME retenue :

```text
aide_ADEME = min(aide_formule, aide_plafond)
```

Le résultat est borné à zéro si la production, la surface ou le CAPEX sont nuls.

CAPEX net :

```text
CAPEX_net = CAPEX_brut - aide_ADEME - autres_aides_publiques
```

### 23.3 Coût de chaleur solaire type HelioEco

Le calcul reprend une logique P1/P2/P4.

Coût moyen de l’énergie de référence sur la durée d’analyse :

```text
facteur_moyen_inflation =
    ((1 + inflation)^duree - 1) / (duree * inflation)
```

si `inflation = 0`, ce facteur vaut `1`.

```text
cout_reference_moyen =
    cout_energie_reference / rendement_appoint_reference
  * facteur_moyen_inflation
```

Poste P1 auxiliaires :

```text
P1_annuel = ratio_auxiliaires * Q_solaire_valorisee * cout_electricite
P1 = P1_annuel / Q_solaire_valorisee
```

Poste P2 maintenance :

```text
P2_annuel = cout_maintenance_m2_an * S
P2 = P2_annuel / Q_solaire_valorisee
```

Poste P4 investissement net :

```text
P4 = CAPEX_net / (Q_solaire_valorisee * duree_analyse)
```

Coût de chaleur solaire :

```text
cout_chaleur_solaire = P1 + P2 + P4
```

Économies annuelles brutes :

```text
economies_annuelles =
    Q_solaire_valorisee * cout_reference_moyen
  - P1_annuel
  - P2_annuel
```

Temps de retour brut :

```text
TRB = CAPEX_net / economies_annuelles
```

si les économies annuelles sont négatives ou nulles, le temps de retour est affiché comme non atteint.

Cashflow cumulé :

```text
cashflow_annee_0 = -CAPEX_net
cashflow_annee_n = -CAPEX_net + n * economies_annuelles
```

Limite importante : dans la synthèse multi-énergies V2, l'aide solaire est calculée uniquement sur le préchauffage HT
solaire direct. L'injection BTES n'est pas recomptee dans l'aide solaire ; elle est valorisée côté géothermie via
l'amélioration du COP et l'économie de linéaire de sondes.


### 23.3.1 Comparaison economique 4 scenarios

L'analyse economique compare quatre scenarios :

1. `Reference 100 % gaz` : HT et BT couverts par appoint gaz.
2. `Geothermie seule` : surface solaire forcee a 0 m2, HT gaz, BT par PAC geothermique + appoint BT si besoin.
3. `Geothermie + solaire meme sondes` : solaire HT et injection BTES actifs, lineaire de sondes identique a la geothermie seule.
4. `Geothermie + solaire sondes reduites` : solaire actif, puis reduction du volume/lineaire equivalent de sondes jusqu'a retrouver une performance proche de la geothermie seule.

Cette logique reprend le raisonnement Dim A / Dim B / Dim C : la recharge solaire est un service rendu au systeme geothermique. Elle ne doit pas etre jugee comme une chaleur solaire autonome injectee au sous-sol.

Allocation solaire conservee, appelee Methode A :

```text
E_solaire_total = E_solaire_HT + E_solaire_injectee_BTES
part_HT = E_solaire_HT / E_solaire_total
part_recharge = E_solaire_injectee_BTES / E_solaire_total
```

Si `E_solaire_total = 0`, les deux parts valent zero.

```text
CAPEX_solaire_HT = CAPEX_solaire_net * part_HT
CAPEX_solaire_recharge = CAPEX_solaire_net * part_recharge
P2_solaire_HT = P2_solaire_total * part_HT
P2_solaire_recharge = P2_solaire_total * part_recharge
P4_solaire_HT = P4_solaire_total * part_HT
P4_solaire_recharge = P4_solaire_total * part_recharge
```

Valeur economique de la recharge solaire :

```text
Gain_lineaire_sondes = L_geothermie_seule - L_geothermie_solaire_reduit
Economie_CAPEX_sondes = Gain_lineaire_sondes * cout_sondes_EUR_ml
Economie_elec_PAC =
    (Elec_PAC_geo_seule - Elec_PAC_geo_solaire_reduit) * prix_elec_moyen
Gain_annuel_recharge =
    annuite(Economie_CAPEX_sondes) + Economie_elec_PAC
Cout_annuel_solaire_recharge =
    annuite(CAPEX_solaire_recharge)
  + P2_solaire_recharge
  + P4_solaire_recharge
Bilan_net_recharge = Gain_annuel_recharge - Cout_annuel_solaire_recharge
TRB_recharge = CAPEX_solaire_recharge / Gain_annuel_recharge
```

Il n'y a volontairement pas d'economie P2 proportionnelle aux metres lineaires de sondes economises. Le P2 geothermie reste lie a la puissance PAC, aux auxiliaires, a la regulation et a la maintenance.

### 23.4 Cohérence gaz référence / appoint Mix EnR

Le scénario `100 % gaz` et l'appoint gaz résiduel du scénario `Mix ENR` utilisent le même coût utile moyen du gaz.

Coût gaz utile moyen :

```text
P1_gaz_utile_moyen =
    P1_gaz_PCI / rendement_appoint_gaz
  * facteur_moyen_inflation_gaz
```

Ce coût est utilisé pour :

```text
P1_reference_100pct_gaz = P1_gaz_utile_moyen
P1_appoint_gaz_mix_ENR = P1_gaz_utile_moyen
```

Le coût annuel P1 de l'appoint gaz dans le Mix EnR vaut donc :

```text
P1_appoint_gaz_annuel = Q_appoint_gaz_mix_ENR * P1_gaz_utile_moyen
```

Cela évite de comparer une référence gaz inflationnée avec un appoint gaz Mix EnR resté au coût année 1.

Le P2 gaz est aussi appliqué aux deux scénarios.

Entrée par défaut :

```text
ratio_P2_gaz = 10 EUR/kW.an
```

Pour l'appoint gaz du Mix EnR :

```text
P2_appoint_gaz_annuel = P_appoint_gaz_mix_ENR * ratio_P2_gaz
P2_appoint_gaz_EUR_MWh = P2_appoint_gaz_annuel / Q_appoint_gaz_mix_ENR
```

Pour la référence 100 % gaz :

```text
P2_reference_gaz_annuel = P_reference_100pct_gaz * ratio_P2_gaz
P2_reference_gaz_EUR_MWh = P2_reference_gaz_annuel / Q_reference_100pct_gaz
```

Ce poste est volontairement proportionnel à la puissance installée, car l'entretien/conduite d'une chaufferie gaz
est largement un coût fixe annuel, même lorsque l'appoint fonctionne peu.

### 23.5 Pré-dimensionnement PAC géothermie avant saisie PAC finale

L'interface calcule maintenant le pré-dimensionnement PAC + sondes avant les données PAC finales du calcul horaire.

Puissance de besoin BT :

```text
Pmax_BT = max(Q_BT_h)
```

Puissance PAC de pré-dimensionnement :

```text
P_PAC_predim = Pmax_BT * ratio_PAC
```

avec :

```text
ratio_PAC = P_PAC_%_Pmax / 100
```

Le COP de pré-dimensionnement est calculé avec les hypothèses PAC du bloc de pré-dimensionnement :

```text
COP_predim = f(Tsol_initial, T_cible_BT, approche_condenseur, approche_evaporateur, rendement_Carnot)
```

Le champ de sondes est ensuite pré-dimensionné par :

```text
P_sous_sol = P_PAC_predim * (COP_predim - 1) / COP_predim
Q_sous_sol = Q_BT_PAC_predim * (COP_predim - 1) / COP_predim
```

Contraintes de longueur :

```text
L_puissance = P_sous_sol * 1000 / ratio_puissance_W_ml
L_energie = Q_sous_sol * 1000 / ratio_energie_kWh_ml_an
L_requise = max(L_puissance, L_energie)
```

Si l'option `Utiliser ce pré-dimensionnement sondes` est active, le nombre de sondes et la profondeur utilisés dans
la simulation horaire sont recalés sur ce résultat.

Les données PAC finales du calcul horaire peuvent :

- reprendre directement les hypothèses du pré-dimensionnement ;
- ou être modifiées manuellement dans le bloc suivant.

La puissance nominale PAC du calcul horaire reste pilotée par :

```text
P_PAC_calcul = Pmax_BT * ratio_PAC
```

### 23.6 Étude paramétrique géothermie seule sur la puissance PAC

L'interface peut lancer une étude paramétrique sur `P PAC (% Pmax BT)`.

Convention importante : cette étude est réalisée avec le solaire thermique désactivé.

```text
surface_solaire = 0
Q_solaire_HT = 0
Q_solaire_BTES = 0
```

L'appoint gaz couvre donc :

```text
Q_gaz_HT = Q_besoin_HT
Q_gaz_BT_complement = Q_besoin_BT - Q_BT_PAC
```

Entrées utilisateur :

```text
ratio_min
ratio_max
pas_ratio
```

Pour chaque ratio testé, le code :

1. recalcule `P_PAC = Pmax_BT * ratio` ;
2. recalcule le pré-dimensionnement de sondes si l'option est active ;
3. force la surface solaire à zéro ;
4. relance la simulation horaire 8760 h ;
5. recalcule l'économie et le coût Mix EnR géothermie + appoint gaz.

Sorties principales :

```text
coût_chaleur_Mix_ENR_i
taux_EnR_global_i
couverture_PAC_BT_i
appoint_total_i
```

avec :

```text
couverture_PAC_BT_i =
    Q_BT_PAC_i / Q_besoin_BT
```

```text
appoint_total_i =
    Q_gaz_HT_i + Q_gaz_BT_complement_i
```

### 23.7 Étude paramétrique sur la surface solaire

L'interface peut lancer une étude paramétrique sur la surface solaire thermique.

Entrées utilisateur :

```text
S_min
S_max
pas_S
```

La liste des surfaces testées est :

```text
S_i = S_min + i * pas_S
```

avec ajout de `S_max` si le pas ne tombe pas exactement dessus. Une limite de sécurité de 25 points est appliquée
pour éviter des temps de calcul excessifs.

Pour chaque surface `S_i`, le code :

1. remplace uniquement `surface_capteurs` dans la configuration ;
2. relance la simulation horaire 8760 h ;
3. recalcule l'économie équivalente de sondes à COP annuel équivalent ;
4. recalcule le CAPEX solaire, l'aide solaire et le coût multi-énergies ;
5. stocke les indicateurs de comparaison.

Sorties principales :

```text
coût_chaleur_Mix_ENR_i
taux_EnR_global_i
couverture_solaire_HT_i
```

avec :

```text
couverture_solaire_HT_i =
    Q_prechauffage_HT_solaire_i / Q_besoin_HT
```

```text
taux_EnR_global_i =
    1 - (appoint_HT_i + appoint_BT_i + electricite_PAC_i) / (besoin_HT + besoin_BT)
```

Le coût Mix EnR est recalculé avec les mêmes conventions économiques que le cas principal, y compris le coût gaz
utile moyen inflationné pour l'appoint gaz résiduel.

## 24. Paramètres par défaut principaux

### Capteurs solaires

```text
surface = 1000 m²
capteur par défaut = SunOptimo 245V
fabricant = SunOptimo
eta0 = 0,824
a1 = 2,905 W/m².K
a2 = 0,030 W/m².K²
rendement hydraulique global = 0,90
```

### Ballon solaire

```text
volume = 50 L/m² capteur
T_ambiance = 20 °C
Tmax ballon / bascule BTES = 80 °C
seuil de bascule BTES = Tmax ballon = 80 °C
approche capteur sur ballon = 10 K
approche échangeur ballon-process = 5 K
pertes ballon = modele SOLO2018 detaille, 1 ballon, 10 cm isolant, lambda 0,035 W/m/K
cible max préchauffage HT solaire = 60 °C
```

### BTES

```text
nombre de sondes = 100
profondeur = 100 m
espacement = 5 m
Tsol initiale = 12 °C
Tmin source PAC operationnelle = 5 °C
Tmin GMI = -3 °C
Tmax GMI = 40 °C
Tmax champ = 40 °C
rendement injection = 90 %
```

### PAC

```text
T cible BT = 25 °C
approche condenseur = 2 K
approche évaporateur = 3 K
rendement Carnot = 54 %
COP min = 2
COP max = 8
```

## 25. Hypothèses simplificatrices importantes

Le modèle est volontairement une V1 horaire, pas un outil de dimensionnement détaillé.

Limites actuelles :

- fichier Excel process 8760 h obligatoire pour lancer le calcul dans l'interface ;
- pas de débit d’air explicite dans le moteur ;
- préchauffage HT calculé par ratio de relèvement de température sur un besoin déjà exprimé en kWh ;
- pas de dynamique hydraulique détaillée ;
- pas de pertes réseau détaillées ;
- pas de stratification du ballon ;
- ballon représenté par une température unique ;
- pas de temps de réponse capteur ;
- pas de capacité thermique du circuit solaire ;
- pas de modèle d’échangeur détaillé, seulement des approches fixes ;
- modèle g-functions assuré par `pygfunction` ;
- résistance thermique sonde/sol simplifiée dans le backend `pygfunction` ;
- interférences temporelles détaillées entre sondes limitées au backend `pygfunction` ;
- limites de puissance linéique encore simplifiées par valeurs forfaitaires ;
- modele economique multi-energies simplifie, avec CAPEX/P1/P2/P4 solaire, geothermie PAC et appoint gaz.

## 26. Points à améliorer en V1+

### Enseignements issus de Miceli et al. 2026 sur les BTES solaires

Miceli et al. 2026 montrent qu'une approche g-function peut rester pertinente pour simuler rapidement des BTES sur de
longues durees, mais que la gestion de l'historique des charges devient un sujet numerique majeur. Dans un couplage
solaire + champ de sondes, l'injection estivale et l'extraction hivernale creent de nombreuses transitions de signe.
Une agregation naive des charges peut alors creer des erreurs au moment des transitions charge/decharge.

HelioStock conserve le backend `pygfunction` et son aggregation Claesson-Javed pour le calcul de production. Le parametre
`load_aggregation_mode = "pygfunction_default"` documente ce choix. Le mode `error_control_placeholder` est reserve a une
future implementation inspiree d'un controle d'erreur, mais il ne modifie pas encore les resultats.

Les sorties ajoutent des diagnostics de charge : energie extraite, energie injectee, ratio injection/extraction, nombre
de transitions, indice d'alternance saisonniere, classification du fonctionnement du champ et indicateur `eta_BTES`.
`eta_BTES = energie extraite du sol / energie injectee dans le BTES` est un indicateur de restitution du stockage ; ce
n'est ni un COP PAC ni un rendement global du systeme.

`pygfunction` ne modelise pas explicitement l'isolation superieure d'un vrai BTES, les conditions aux limites complexes,
l'heterogeneite verticale fine, l'hydraulique MIFT serie/parallele detaillee ni l'inertie court terme tube/coulis. Pour un
stockage intersaisonnier peu profond et fortement recharge, HelioStock affiche donc un avertissement de prudence plutot
que d'ajouter une correction thermique arbitraire.

Priorités techniques :

1. Supprimer dans une future version majeure l'alias de compatibilité `solar_ht_direct_kwh` quand les exports historiques ne l'exigeront plus.
2. Renforcer les profils horaires process et les tests de non-régression énergétique.
3. Consolider les limites de puissance d’injection/extraction BTES par mètre de sonde.
4. Consolider le backend `pygfunction` et comparer ensuite avec `GHEtool`.
5. Ajouter une modélisation plus réaliste du ballon : stratification ou au minimum nœuds haut/bas.
6. Ajouter des profils d’exploitation : horaires ouvrés, week-ends, arrêts, saisonnalité process.
7. Ajouter la partie économique géothermie : CAPEX champ de sondes, PAC, appoint, OPEX et valorisation de l’économie de sondes.

## 27. Alignement avec un dimensionnement classique de champ de sondes

La version actuelle aligne le controle technique du champ de sondes sur une trajectoire multiannuelle de 25 ans par defaut.
Les resultats techniques principaux sont lus sur l'annee finale, tandis que l'economie reste calculee sur la trajectoire
multiannuelle complete.

Le critere GMI est distingue du pilotage PAC :

```text
Tmin GMI = -3 C
Tmax GMI = +40 C
Tmin source PAC operationnelle = 5 C par defaut
```

La Tmin operationnelle peut donc rester plus prudente que le seuil GMI. Les resultats distinguent les heures sous Tmin
operationnelle, les heures hors GMI, la temperature source PAC minimale de l'annee finale et la temperature maximale de
fluide en injection.

Les temperatures exposees ne sont pas interchangeables :

```text
T_paroi_forage_C
T_source_PAC_pour_COP_C
T_source_PAC_fin_heure_C
T_evaporateur_PAC_C
T_fluide_injection_C
T_fluide_entree_echangeur_geo_C
```

Le couplage horaire reste explicite : le COP est calcule avec la temperature disponible pendant l'heure, puis la charge
horaire est appliquee dans `pygfunction`. La temperature fin d'heure peut donc etre legerement plus basse que le seuil
operationnel, ce qui doit etre interprete comme un diagnostic de derive thermique et non comme la temperature qui a servi
au COP de cette meme heure.

Le predimensionnement prudent utilise maintenant :

```text
ratio puissance predimensionnement = 50 W/ml
ratio energie annuelle predimensionnement = 100 kWh/ml.an
facteur securite = 1,20
```

HelioStock distingue les ratios de predimensionnement des limites operationnelles de simulation. Les premiers servent a
proposer un champ initial ; les secondes bornent les puissances horaires extremes. Les limites dures standard sont :

```text
limite dure extraction simulation = 70 W/ml
limite dure injection simulation = 80 W/ml
```

Les alertes signalent les zones de vigilance sans bloquer systematiquement le calcul :

```text
alerte extraction = 50 W/ml
alerte forte extraction = 60 W/ml
alerte injection = 60 W/ml
alerte forte injection = 80 W/ml
```

Ces limites horaires sont volontairement plus hautes que les ratios de predimensionnement. La validation physique repose
d'abord sur la temperature source, le critere GMI -3/+40 C, la trajectoire sur 25 ans, le COP de l'annee finale et la
couverture PAC. La geometrie du champ et les interactions temporelles doivent etre consolidees par une etude
geothermique detaillee.

L'outil conserve ses specificites : process HT/BT, solaire thermique via ballon journalier, injection solaire seulement
apres saturation du ballon, comparaison gaz / geothermie / geothermie + solaire. Il reste un outil d'opportunite et ne
remplace pas une etude avec TRT, plan de champ reel, hydraulique et ingenierie dediee.
