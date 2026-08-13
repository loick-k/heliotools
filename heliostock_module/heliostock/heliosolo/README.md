# HelioSOLO - reconstitution SOLO 2018

Ce module est centré sur une reconstitution Python/Streamlit de la logique SOLO 2018 pour le solaire thermique ECS.

La notice méthodologique complète est disponible dans `NOTICE_HELIOSOLO.md` et dans l'onglet `4) Notice` de l'interface.

## Structure

- `streamlit_heliosolo_app.py` : adaptateur Streamlit HelioTools.
- `NOTICE_HELIOSOLO.md` : audit et notice méthodologique.
- `solo2018_rebuild/core/solo_v0_engine.py` : moteur de calcul mensuel.
- `solo2018_rebuild/meteo/epw_reader.py` : lecture EPW et préparation météo mensuelle.

## Démarrage autonome

```bash
streamlit run heliostock_module/demo_app.py
```

## Logique retenue

- Les entrées de calcul sont explicites : `VECS`, `TECS`, `TEF`, `TExt`, `R global plan`.
- Les données mensuelles servent au calcul sur jour moyen.
- Le moteur reprend la logique SOLO avec stockage, transfert, pertes et couverture non linéaire.
- HelioSOLO n'est pas le logiciel officiel SOLO 2018 ; c'est une reconstitution intégrée à HelioTools.

## Suite

1. Caler les paramètres sur des cas SOLO de référence.
2. Valider mois par mois les écarts et conventions.
3. Mutualiser progressivement les briques communes avec HelioNOP et HelioDyn.
