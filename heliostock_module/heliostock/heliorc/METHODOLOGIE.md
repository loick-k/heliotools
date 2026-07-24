# Méthodologie HelioRC

Cette version reprend le classeur **NO_STH_RCU_v5.3**, daté du 16 décembre 2025, et les principes décrits dans la présentation ADEME **Solaire thermique sur RCU - Outil de prédimensionnement**.

## Domaine d'emploi

- Centrale solaire avec stockage journalier.
- Capteurs plans vitrés haute performance, inclinaison fixe.
- Taille de champ supérieure à 100 m².
- Fraction solaire indicative de 10 à 30 %.
- Usage en pré-étude, avant une étude de faisabilité et une modélisation dynamique.

Sont hors cadre : stockage intersaisonnier, tracker, capteurs plans sous vide, recharge géothermique, configurations hydrauliques complexes et implantations atypiques.

## Besoins mensuels

Deux voies sont proposées :

1. saisie directe des 12 besoins mensuels du RCU, pertes comprises ;
2. estimation depuis les besoins annuels de chauffage et d'ECS des abonnés.

La répartition du chauffage est proportionnelle à un proxy de degrés-jours construit avec la température minimale de juin à août. L'ECS est modulée par les coefficients mensuels du classeur :

`1,10 ; 1,10 ; 1,10 ; 1,10 ; 1,10 ; 0,85 ; 0,75 ; 0,75 ; 0,90 ; 1,05 ; 1,10 ; 1,10`.

Le mode **Excel v5.3** utilise des pertes annuelles égales à `(chauffage + ECS) × (1 - rendement)`. Le mode **présentation** calcule les pertes par `(chauffage + ECS) / rendement - (chauffage + ECS)`.

## Profil de production solaire

Le profil mensuel est fondé sur l'irradiation globale dans le plan optimal, issue du tableau météorologique du classeur. Elle est multipliée par les 12 coefficients correctifs FPC constants de la version 5.3, puis normalisée sur son maximum.

La production mensuelle est :

`production_mois = talon_de_dimensionnement × besoin_mensuel_minimal × profil_solaire_mois`.

## Productivité et surface

La productivité annuelle est calculée par :

`P = (0,4818 G - 503,1 Bé + 1,1244 Bé G - 199,6) × (1 + 0,014 × (55 - Tm))`

avec :

- `G` : irradiation globale horizontale annuelle en kWh/m².an ;
- `Bé` : part des besoins de mai à septembre ;
- `Tm` : température moyenne estivale du réseau.

La surface est la production solaire annuelle divisée par la productivité annuelle.

## Ratios techniques

- stockage : `0,2 m³/m²`, arrondi par défaut à la dizaine inférieure comme dans le classeur ;
- emprise : `2,5 m² de terrain / m² de capteur` ;
- nombre de panneaux indicatif : surface divisée par 15 m² ;
- distance : formule du classeur en mode strict, ou 200 m/MW avec 1 kW/m² en mode présentation.

## Économie

Le coût surfacique suit la fonction par morceaux du classeur :

- jusqu'à 100 m² : 1 500 €/m² ;
- 100 à 1 000 m² : décroissance linéaire ;
- 1 000 à 1 500 m² : seconde décroissance linéaire ;
- au-delà : `-159,1 ln(S) + 1 990,2` €/m².

L'aide est calculée avec les forfaits 2025 du classeur : 63 €/MWh en zone Nord, 56 €/MWh en zone Sud et 50 €/MWh en zone Méditerranée, avec une valeur indicative au-delà de 1 500 m² et un plafond total de 65 % du CAPEX.

Le LCOH aidé est la somme de :

- P1' : 1,5 % du prix de l'électricité ;
- P2/P3 : 1 % du CAPEX par an, ramené au MWh solaire ;
- P4 : facteur de récupération du capital sur 30 ans, avec 5 % sous 500 m² et 6 % au-delà par défaut.

## Interprétation

Une opportunité est considérée comme favorable à approfondir lorsque la fraction solaire atteint au moins 10 % et la surface au moins 250 m², sous réserve que le réseau fonctionne en été et qu'aucune autre EnR&R ne soit excédentaire sur ce talon. La présentation ADEME recommande de passer ensuite à une étude de faisabilité et à un outil dynamique tel qu'EnRSim.
