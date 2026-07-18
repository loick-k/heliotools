# Notes développeur HelioStock

## Rôle du module

HelioStock est un outil de prédimensionnement pour comparer des scénarios de chaleur renouvelable :

- scénario A : géothermie seule pour le besoin basse température ;
- scénario B : géothermie avec recharge solaire du champ et solaire thermique haute température ;
- scénario C : même logique que le scénario B, avec recherche d'un linéaire de sondes réduit.

Le backend géothermique de production est `pygfunction`. Le modèle reste horaire et conserve la possibilité de simuler la trajectoire technique sur 25 ans.

## Flux de calcul principal

Le flux Streamlit passe par :

1. `streamlit_module.py` : formulaire, authentification portail, lancement du calcul, journal de performance.
2. `app_service.py` : construction de la requête et séparation durée technique / durée économique.
3. `scenarios.py::run_hourly_scenario` : orchestration des scénarios A, B et C.
4. `hourly_engine.py::simulate_hourly` : simulation horaire physique.
5. `postprocess.py` et `scenario_metrics.py` : agrégations annuelles, mensuelles et métriques compactes.
6. `ui_results.py` et `ui_economics.py` : affichage des KPI, graphes et tableaux.

## Résultats horaires complets et métriques compactes

Deux niveaux de résultats coexistent.

Les résultats horaires complets (`HourlyResult`) sont utiles pour :

- les graphes horaires ;
- l'année affichée ;
- les exports détaillés ;
- les analyses mensuelles.

Les métriques compactes sont préférées pour :

- les études paramétriques ;
- l'économie de sondes ;
- les boucles de simulation lourdes ;
- les coûts multiannuels qui n'ont pas besoin du détail heure par heure.

Éviter de créer un DataFrame horaire 25 ans dans une boucle paramétrique si les KPI annuels suffisent.

## Durée technique et durée économique

Ne pas confondre :

- `technical_simulation_years` ou `multiyear_years` : durée physique de simulation du champ ;
- `economics.analysis_years` : durée d'analyse économique.

Une référence de simulation ou un cache physique doit utiliser la durée technique réelle. `analysis_years` ne doit pas décider du nombre d'années envoyées à `pygfunction`.

## Conventions de signe géothermie

Dans les résultats horaires :

- extraction PAC depuis le sol : charge positive ;
- injection solaire dans le sol : charge négative ;
- `q_net_W_m` suit cette convention nette.

Les KPI utilisateur doivent rester prudents : afficher les énergies injectées/extraites, les températures, les heures sous seuil, le critère GMI et les puissances linéiques. Ne pas présenter d'indicateurs avancés de modèle BTES détaillé comme une validation métier.

## Conventions de température

Ne pas mélanger :

- `T_source_PAC_pour_COP_C` : température utilisée pour calculer le COP pendant l'heure ;
- `T_source_PAC_fin_heure_C` ou `T_source_PAC_C` selon le DataFrame : diagnostic de fin d'heure après application de la charge ;
- `T_paroi_forage_C` : température de paroi forage ;
- `T_evaporateur_PAC_C` : température côté évaporateur.

Les critères de régulation s'interprètent avec la température source utilisée par la PAC. Les diagnostics de dérive thermique s'interprètent avec la température de fin d'heure et la trajectoire multiannuelle.

## Ajouter une nouvelle métrique

Avant d'ajouter une métrique :

1. Identifier si elle est horaire, annuelle, année finale ou économique.
2. La calculer dans le niveau le plus léger possible.
3. Ajouter un test sur un cas simple.
4. Vérifier qu'elle ne force pas la conversion d'une simulation 25 ans complète en DataFrame dans une boucle.
5. Documenter si la grandeur est un KPI métier ou seulement un diagnostic.

## Ajouter une nouvelle colonne

Pour une colonne critique utilisée par plusieurs modules :

- documenter le nom exact ;
- éviter les variantes proches ;
- ajouter un test si elle est utilisée dans l'économie, les paramétriques ou l'économie de sondes.

Les colonnes historiques d'export ne doivent pas être renommées sans compatibilité.

## Tests

Depuis `heliostock_module` :

```powershell
python -m compileall heliostock
python -m pytest -q
```

Les tests qui dépendent réellement de `pygfunction` doivent appeler `skip_if_no_pygfunction()` afin que l'absence de backend soit visible comme un skip pytest, pas comme un retour silencieux.

## Archive propre

Avant livraison :

- supprimer `__pycache__` ;
- supprimer `.pytest_cache` ;
- ne pas inclure `.git` ;
- ne pas inclure de secrets Streamlit ;
- ne pas inclure de dossier projet imbriqué obsolète.

## Limites connues

HelioStock ne remplace pas une étude géothermique détaillée avec TRT, ingénierie hydraulique et modélisation fine du sous-sol. Le modèle ne doit pas être interprété comme un jumeau numérique de stockage intersaisonnier détaillé.
