# Notice méthodologique HelioSOLO

Cette notice documente la reconstitution HelioSOLO intégrée dans HelioTools et son écart avec l'algorithme SOLO 2018 décrit dans `SOLO_2018_Principes_et_Algorithmes_V1_1.pdf`.

HelioSOLO n'est pas le logiciel officiel SOLO 2018. C'est une reconstitution Python/Streamlit destinée à rendre les hypothèses plus lisibles, à faciliter les tests et à préparer les passerelles avec HelioNOP, HelioDyn et les futurs modules économiques.

## Périmètre du modèle

HelioSOLO reste un modèle mensuel de type SOLO 2018.

Il ne s'agit pas d'une simulation horaire dynamique. Le calcul travaille sur des jours moyens mensuels : besoin ECS moyen, température d'eau froide moyenne, température extérieure moyenne et irradiation moyenne dans le plan des capteurs.

La philosophie reprise est celle de SOLO 2018 : obtenir rapidement un ordre de grandeur robuste pour une installation solaire thermique collective, sans passer par une simulation hydraulique détaillée.

## Éléments repris de SOLO 2018

### Équation mensuelle centrale

Le calcul mensuel conserve la logique SOLO : production solaire utile calculée à partir du besoin de référence, du rayonnement disponible, de la surface de capteurs, des pertes du capteur, du transfert primaire, de l'échangeur et du stockage.

Les résultats sont produits mois par mois puis agrégés à l'année.

### Capteurs solaires

HelioSOLO accepte les paramètres de capteurs sous forme `B/K` ou sous forme issue d'essais normalisés `eta0/a1/a2`.

Quand les coefficients `eta0/a1/a2` sont utilisés, le code les convertit en couple équivalent `B/K` par régression sur plusieurs écarts de température. Cette logique reprend l'esprit de SOLO 2018, qui ramène les performances capteur vers une formulation exploitable par le calcul mensuel.

### Correction d'incidence

Le rayonnement disponible dans le plan des capteurs peut être corrigé par un coefficient d'incidence dépendant de l'inclinaison, de l'orientation, de la latitude, du mois et d'heures représentatives.

### Circuit primaire et échangeur

Le moteur tient compte des pertes côté primaire, du type de circulation, de l'efficacité de régulation, de l'échangeur solaire et de la dégradation de transfert entre capteurs et stockage.

### Stockage solaire

HelioSOLO reprend les deux logiques de définition du stockage :

- une valeur globale de constante de refroidissement du stock ;
- une définition détaillée par volume, surface équivalente, épaisseur d'isolant, conductivité de l'isolant et correction de ponts thermiques.

La géométrie standard du ballon reprend l'hypothèse cylindrique verticale avec `H/D = 2`.

La constante `CRStockSolaire` est calculée en `Wh/L/K/jour`. Le code convertit explicitement le volume en litres dans la constante finale afin d'éviter une erreur de facteur 1000 entre m3 et litres.

### Bouclage sanitaire

HelioSOLO reprend les grands modes de SOLO 2018 :

- pas de pertes de bouclage ;
- saisie directe des pertes ;
- calcul par débit de bouclage et écart de température ;
- calcul par longueur de boucle et coefficient linéique ;
- qualification simplifiée de la boucle : bonne, moyenne ou mauvaise.

Quand le bouclage est considéré comme solarisable indirectement, le besoin solaire de référence est augmenté via une température ECS équivalente, plafonnée par la température maximale du stockage solaire.

### Eau technique CESCET

Le mode CESCET est représenté comme un CESC complété par un circuit d'eau technique et un échangeur aval.

Le calcul applique une correction de température côté eau technique, puis retranche les pertes du circuit d'eau technique. Cette logique reprend le principe de SOLO 2018 : l'échangeur et les pertes aval réduisent l'énergie solaire effectivement livrée à l'ECS.

### Production primaire solaire

La production primaire est calculée comme la production utile augmentée des pertes de stockage solaire. Cela permet de distinguer la production utile livrée à l'ECS et l'énergie produite en amont du ballon.

## Adaptations HelioTools

### Interface et usages

L'interface Streamlit n'est pas une reproduction écran par écran de SOLO 2018. Elle vise une lecture plus directe des hypothèses, des résultats mensuels et des contrôles métier.

Les exports et sauvegardes JSON sont des ajouts HelioTools.

### Typologies d'établissement et unités

SOLO 2018 attend principalement des grandeurs physiques : volume ECS, température ECS, température d'eau froide, pertes de bouclage, surface, stockage, etc.

HelioSOLO ajoute une couche d'aide par typologie d'établissement et unité de référence pour estimer plus vite certains volumes ou pertes.

Cette adaptation est utile pour le prédimensionnement, mais elle ne doit pas être confondue avec une grandeur physique mesurée. Pour un site atypique, il faut privilégier une saisie explicite des besoins et des pertes de bouclage.

### Pertes de bouclage par typologie

La différence la plus importante porte sur le bouclage.

Dans le cœur SOLO, le bouclage est plutôt ramené à un coefficient global ou à des pertes connues. Dans HelioSOLO, les modes qualitatifs `bon`, `moyen`, `mauvais` peuvent être convertis à partir d'un nombre d'unités estimé :

`nombre d'unités = volume ECS journalier / volume ECS par unité de référence`

puis :

`longueur de boucle = nombre d'unités x longueur de boucle par unité`

et enfin :

`KG boucle = longueur de boucle x coefficient linéique`

C'est une aide de saisie, pas une mesure. Elle peut être pertinente pour un ordre de grandeur, mais elle doit être remplacée par une longueur réelle, un débit mesuré ou une perte saisie si les données sont disponibles.

### Température d'eau froide et CESCET

HelioSOLO permet plusieurs sources pour la température d'eau froide :

- saisie annuelle ;
- saisie mensuelle ;
- méthode ESM2 ;
- méthode ESM2 + 3 °C.

Pendant le développement, un risque avait été identifié : dans certains chemins, quand la température d'eau froide n'était pas issue de la méthode ESM2 ou ESM2 + 3 °C, le calcul CESCET pouvait se comporter comme un calcul ECS sanitaire simple.

Ce point a été corrigé : la correction eau technique est maintenant appliquée à partir de la température mensuelle utilisée par le mois, quelle que soit son origine. Une température d'eau froide saisie manuellement reste donc compatible avec le calcul CESCET.

### Météo

La reconstitution conserve une logique météo mensuelle. Elle peut utiliser des profils préremplis ou des données EPW importées dans le module.

Cette partie n'est pas encore totalement mutualisée avec la bibliothèque météo commune de HelioTools. C'est un point de convergence futur avec HelioNOP et HelioDyn.

### Stock solaire homogène

Comme SOLO 2018, HelioSOLO reste un calcul mensuel avec stockage représenté de façon globale. Il ne simule pas une stratification horaire détaillée du ballon.

La stratification dynamique 3 nœuds relève plutôt de HelioDyn, pas de HelioSOLO.

### Schémas hydrauliques

Le module actuel ne couvre pas encore de façon exhaustive toutes les variantes hydrauliques possibles. Les choix disponibles sont ceux nécessaires à la reconstitution actuelle et aux cas de test prioritaires.

## Contrôles et limites d'interprétation

Les résultats doivent être interprétés comme une note d'opportunité ou une vérification de cohérence, pas comme une étude d'exécution.

Points sensibles :

- qualité des besoins ECS mensuels ;
- température d'eau froide retenue ;
- pertes de bouclage ;
- efficacité d'échangeur ;
- circuit eau technique en CESCET ;
- volume de stockage ;
- fraction solaire élevée ;
- sites avec usages très intermittents.

Lorsque les pertes de bouclage sont importantes ou mal connues, elles peuvent dominer le résultat. Dans ce cas, il faut éviter les modes qualitatifs et saisir une perte mesurée ou une géométrie réaliste.

## Lecture rapide des différences

| Sujet | SOLO 2018 | HelioSOLO |
|---|---|---|
| Pas de temps | Mensuel, jour moyen | Mensuel, jour moyen |
| Capteurs | Formulation B/K, conversion possible | B/K et conversion eta0/a1/a2 |
| Stock solaire | Constante CR globale ou détaillée | Même logique, avec correction explicite litres/m3 |
| Bouclage | Plusieurs modes physiques/simplifiés | Même logique + aide par typologie et unité |
| CESCET | Circuit eau technique et échangeur aval | Repris, avec correction robuste quelle que soit la source TEF |
| Météo | Données mensuelles | Données mensuelles, EPW/module interne |
| Hydraulique détaillée | Semi-simplifiée | Semi-simplifiée |
| Simulation horaire | Non | Non |
| Stratification ballon | Non détaillée | Non détaillée |

## Positionnement dans HelioTools

HelioSOLO sert à reconstituer et auditer une logique SOLO 2018.

HelioNOP sert à produire une note d'opportunité.

HelioDyn sert à simuler dynamiquement des profils horaires, avec ou sans couplage solaire-géothermie.

À terme, les briques communes à mutualiser sont :

- besoins ECS ;
- température d'eau froide ;
- bibliothèque capteurs ;
- pertes de bouclage ;
- hypothèses économiques ;
- exports PDF.
