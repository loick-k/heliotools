# Notice méthodologique HelioSOLO

Cette notice documente la reconstitution HelioSOLO intégrée dans HelioTools et ses écarts avec l'algorithme SOLO 2018 décrit dans `SOLO_2018_Principes_et_Algorithmes_V1_1.pdf`.

HelioSOLO n'est pas le logiciel officiel SOLO 2018. C'est une reconstitution Python/Streamlit destinée à rendre les hypothèses plus lisibles, faciliter les tests et préparer les passerelles avec HelioNOP, HelioDyn et les futurs modules économiques.

## Positionnement physique

HelioSOLO reste un modèle mensuel de prédimensionnement solaire thermique ECS.

Il ne s'agit pas d'une simulation horaire dynamique. Le calcul travaille sur des jours moyens mensuels : volume ECS, température d'eau froide, température ECS, pertes de bouclage, température extérieure et irradiation dans le plan des capteurs.

Le résultat doit donc être lu comme un ordre de grandeur robuste pour note d'opportunité ou comparaison d'hypothèses, pas comme une étude hydraulique d'exécution.

## Éléments repris de SOLO 2018

### Équation mensuelle centrale

Le moteur conserve la logique SOLO : la production solaire utile est calculée mois par mois à partir du besoin de référence, du rayonnement disponible, de la surface capteurs, des pertes capteurs, du transfert primaire, de l'échangeur et du stockage.

Les résultats mensuels sont ensuite agrégés à l'année.

### Capteurs solaires

HelioSOLO accepte deux familles de paramètres :

- formulation `B/K` ;
- coefficients d'essais `eta0/a1/a2`.

Quand `eta0/a1/a2` sont fournis, ils sont convertis vers un couple équivalent `B/K` par régression sur plusieurs écarts de température. Cette conversion reprend l'esprit du calcul SOLO, mais reste une approximation pratique : elle ne remplace pas une simulation horaire détaillée du capteur.

### Correction d'incidence

Le rayonnement disponible peut être corrigé selon l'inclinaison, l'orientation, la latitude, le mois et des heures représentatives. Le modèle travaille sur une correction mensuelle, pas sur une trajectoire solaire horaire complète.

### Circuit primaire et échangeur

Le calcul tient compte :

- du type de circulation ;
- des pertes du circuit primaire ;
- de l'efficacité de régulation ;
- du type d'échangeur solaire ;
- de la dégradation de transfert entre capteurs et stockage.

Ces grandeurs servent à corriger la production solaire mensuelle. Elles ne décrivent pas la régulation instantanée ni les transitoires hydrauliques.

### Stockage solaire

HelioSOLO reprend les deux approches de stockage :

- constante de refroidissement globale ;
- définition détaillée par volume unitaire, nombre de ballons, surface équivalente, épaisseur d'isolant, conductivité de l'isolant et correction de ponts thermiques.

La géométrie détaillée repose sur un ballon cylindrique vertical avec `H/D = 2`. La constante `CRStockSolaire` est exprimée en `Wh/L/K/jour`. Le calcul utilise explicitement le volume en litres pour éviter l'erreur classique de facteur 1000 entre m3 et litres.

Le stock reste toutefois représenté de façon globale. Il n'y a pas de stratification dynamique ni de température haute/basse du ballon dans HelioSOLO.

### Bouclage sanitaire

Les modes physiques ou simplifiés suivants sont représentés :

- aucun bouclage ;
- saisie directe des pertes ;
- calcul par débit et écart de température ;
- calcul par longueur et coefficient linéique ;
- qualification simplifiée de la boucle : bonne, moyenne ou mauvaise.

Quand le bouclage est solarisable indirectement, le besoin solaire de référence est augmenté par une température ECS équivalente, plafonnée par la température maximale de stockage.

## Adaptations HelioTools

### Typologies et unités de référence

SOLO 2018 manipule surtout des grandeurs physiques. HelioSOLO ajoute une couche d'aide par typologie d'établissement et unité de référence pour accélérer la saisie.

Cette couche est pratique, mais elle ne doit pas être confondue avec une mesure. Pour un site atypique, il faut privilégier :

- un volume ECS mesuré ;
- une température eau froide cohérente ;
- une perte de bouclage mesurée ou calculée sur une longueur réelle.

### Pertes de bouclage par typologie

C'est un écart important avec une lecture stricte de SOLO 2018.

Dans HelioSOLO, les modes `bon`, `moyen` et `mauvais` peuvent convertir un volume ECS en nombre d'unités :

`nombre d'unités = volume ECS journalier / volume ECS par unité de référence`

puis :

`longueur de boucle = nombre d'unités x longueur de boucle par unité`

et enfin :

`KG boucle = longueur de boucle x coefficient linéique`

Cette approche donne un ordre de grandeur, mais elle peut fortement biaiser le résultat si le bâtiment ne correspond pas à la typologie choisie. Les pertes de bouclage doivent être vues comme une hypothèse de premier rang.

### Température d'eau froide et CESCET

HelioSOLO permet plusieurs sources de température d'eau froide :

- saisie annuelle ;
- saisie mensuelle ;
- méthode ESM2 ;
- méthode ESM2 + 3 °C.

Pendant le développement, un risque avait été identifié : lorsque la température d'eau froide n'était pas issue d'ESM2 ou ESM2 + 3 °C, certains chemins de calcul en eau technique CESCET pouvaient revenir à un comportement proche du CESC sanitaire simple.

Ce point a été corrigé : la correction eau technique utilise désormais la température mensuelle réellement retenue, quelle que soit son origine. Une température d'eau froide saisie manuellement reste donc compatible avec le calcul CESCET.

### Météo

Le module utilise des profils mensuels et peut lire des données EPW. La météo n'est pas encore totalement mutualisée avec les bibliothèques météo utilisées par HelioNOP et HelioDyn.

À terme, la bonne cible est une source météo commune pour HelioTools, afin d'éviter des écarts entre modules.

### Exports

Les exports JSON, CSV et PDF sont des ajouts HelioTools. Le PDF utilise le moteur commun HelioTools pour garder une mise en page homogène avec les autres modules.

## Audit physique du moteur actuel

### Besoin ECS

Le besoin ECS est calculé à partir du volume, de la température ECS de référence et de la température d'eau froide :

`Besoin ECS = Volume x capacité thermique de l'eau x (T_ECS - T_EF)`

Le modèle est physiquement cohérent si les volumes et températures sont cohérents. L'incertitude principale vient rarement de la formule : elle vient plutôt de la qualité du profil de consommation.

### Bouclage

Les pertes de bouclage peuvent devenir dominantes. Si elles sont surestimées, le besoin solarisable et la production solaire peuvent être artificiellement élevés. Si elles sont sous-estimées, le projet peut paraître moins pertinent qu'il ne l'est.

Pour les notes d'opportunité, le mode typologique est acceptable. Pour une étude avancée, il faut privilégier une donnée mesurée ou une longueur réelle.

### Stockage

Le stockage est représenté par une constante de refroidissement mensuelle. C'est cohérent avec l'esprit SOLO, mais cela ne permet pas d'observer :

- la stratification du ballon ;
- les épisodes horaires de saturation ;
- les cycles courts de charge/décharge ;
- la température réelle en haut et en bas de ballon.

Ces phénomènes relèvent plutôt d'HelioDyn.

### Production solaire

La production solaire mensuelle est cohérente pour comparer des surfaces, volumes et hypothèses de bouclage. Elle devient moins précise lorsque :

- la fraction solaire estivale est très élevée ;
- le stockage est très faible ;
- le besoin est très intermittent ;
- les pertes de bouclage sont mal connues ;
- le schéma hydraulique réel diffère fortement du schéma représenté.

### CESCET

Le CESCET ajoute une correction pour l'eau technique et les pertes aval. C'est utile pour éviter d'assimiler une installation eau technique à une installation sanitaire directe.

Le modèle reste toutefois mensuel. Il ne vérifie pas les débits instantanés, les températures de retour réelles, ni la stratégie de régulation de l'échangeur aval.

### Contrôles numériques

Le code applique des sécurités simples :

- valeurs négatives évitées sur les énergies et pertes ;
- volumes et surfaces bornés positivement ;
- constantes de refroidissement positives ;
- températures équivalentes plafonnées par le stockage ;
- gestion dédiée des mois et des lignes annuelles.

Ces garde-fous évitent les erreurs numériques évidentes, mais ils ne remplacent pas le jugement métier.

## Différences principales avec SOLO 2018

| Sujet | SOLO 2018 | HelioSOLO |
|---|---|---|
| Pas de temps | Mensuel, jour moyen | Mensuel, jour moyen |
| Capteurs | Formulation SOLO B/K | B/K et conversion `eta0/a1/a2` |
| Stock solaire | Constante globale ou détaillée | Même logique, avec vigilance explicite sur les unités |
| Bouclage | Modes physiques et simplifiés | Même base + aide par typologie et unité |
| CESCET | Circuit eau technique et échangeur aval | Repris, avec correction robuste quelle que soit la source de température d'eau froide |
| Météo | Données mensuelles | Profils mensuels et EPW interne |
| Hydraulique fine | Simplifiée | Simplifiée |
| Simulation horaire | Non | Non |
| Stratification ballon | Non détaillée | Non détaillée |

## Bonnes pratiques d'utilisation

Pour une première approche, HelioSOLO est pertinent si :

- le besoin ECS est connu ou raisonnablement estimé ;
- la température d'eau froide est cohérente ;
- les pertes de bouclage sont maîtrisées ;
- la fraction solaire reste dans un domaine raisonnable ;
- le schéma hydraulique choisi correspond au principe réel.

Pour fiabiliser une étude, il faut en priorité améliorer :

1. le profil de besoin ECS ;
2. les pertes de bouclage ;
3. la température d'eau froide ;
4. les caractéristiques capteur ;
5. le volume et les pertes du stockage ;
6. la cohérence du schéma hydraulique.

## Positionnement dans HelioTools

HelioSOLO sert à reconstituer et auditer une logique SOLO 2018.

HelioNOP sert à produire une note d'opportunité.

HelioDyn sert à simuler dynamiquement des profils horaires, avec ou sans couplage solaire-géothermie.

Les briques à mutualiser progressivement sont :

- besoins ECS ;
- température d'eau froide ;
- météo ;
- bibliothèque capteurs ;
- pertes de bouclage ;
- stockage solaire ;
- hypothèses économiques ;
- exports PDF.
