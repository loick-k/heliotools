# Architecture HelioStock

Ce document sert de carte de travail pour maintenir le code sans mélanger interface, orchestration, physique et économie.

## Flux principal

```text
streamlit_module.py
  -> assemble la page Streamlit
  -> appelle les formulaires, le service de calcul et le rendu des résultats

ui_forms.py
  -> collecte les hypothèses utilisateur
  -> renvoie des dataclasses d'entrée

app_service.py
  -> transforme les hypothèses UI en ScenarioInputs
  -> lance le scénario principal
  -> lance éventuellement les études paramétriques
  -> renvoie un HourlyCalculationResult

scenarios.py
  -> orchestre les simulations physiques avec/sans solaire
  -> calcule les indicateurs annuels et multiannuels
  -> construit la comparaison économique des scénarios

borefield_savings.py
  -> cherche le linéaire équivalent économisable avec recharge solaire

hourly_engine.py / btes_models.py
  -> calcul physique horaire
  -> état du ballon solaire, du BTES et de la PAC

economics.py
  -> CAPEX, P1/P2/P4, aides, coût de chaleur

ui_results.py / ui_economics.py / charts.py
  -> rendu Streamlit des résultats
  -> tableaux, métriques, graphiques
```

## Responsabilités par fichier

- `streamlit_module.py` : page Streamlit principale, bouton de calcul, stockage du dernier résultat en session.
- `ui_forms.py` : formulaires de saisie Streamlit, upload EPW/besoins, panneaux solaire/geothermie/economie/parametriques.
- `app_service.py` : couche applicative indépendante de Streamlit. C'est le bon endroit pour ajouter cache, profilage et exécution batch.
- `inputs.py` : dataclasses d'entrée et validations simples.
- `engine.py` : configurations physiques communes et fonctions partagées.
- `hourly_engine.py` : boucle horaire, allocation solaire, PAC, BTES, appoints.
- `btes_models.py` : modèle champ de sondes via `pygfunction`.
- `scenarios.py` : assemblage des scénarios, comparaison avec/sans solaire, multiannuel, économie de sondes.
- `borefield_savings.py` : solveur de réduction équivalente de champ de sondes.
- `economics.py` : calcul économique pur.
- `postprocess.py` : agrégations annuelles, mensuelles, monotones et conversions en DataFrame.
- `charts.py` : fonctions Altair uniquement.
- `ui_results.py` : rendu des résultats physiques, onglets, diagnostics et paramétriques.
- `ui_economics.py` : rendu de l'onglet économie.
- `ui_inputs.py` : constantes d'interface et hypothèses fixes affichées.
- `load_profiles.py` : lecture et conversion des profils de besoins.
- `epw_reader.py` : lecture météo EPW.
- `geothermal_design.py` : prédimensionnement PAC/champ de sondes.

## Règles de séparation

- Une fonction physique ne doit pas importer `streamlit`.
- Une fonction économique ne doit pas dépendre d'un widget ou de `session_state`.
- Les modules `ui_*` peuvent importer Streamlit, mais ne doivent pas contenir de logique physique lourde.
- `app_service.py` peut orchestrer les calculs, mais ne doit pas afficher.
- `scenarios.py` peut appeler le moteur physique et l'économie, mais ne doit pas lire de fichiers utilisateur.
- `charts.py` doit rester déclaratif : DataFrame entrant, graphique sortant.

## Prochaines optimisations naturelles

1. Ajouter un cache de simulation dans `app_service.py` ou dans un futur `simulation_cache.py`.
2. Ajouter un profilage par étape dans `app_service.py`.
3. Sortir la lecture météo/besoins vers un `input_service.py` si un mode batch hors Streamlit devient prioritaire.
4. Découper `scenarios.py` en `scenario_runner.py`, `scenario_metrics.py` et `economic_comparison.py`.
5. Ajouter des tests unitaires dédiés aux formulaires avec Streamlit mocké si l'interface devient plus complexe.
