# Reconstitution SOLO 2018 (ECS)

Ce projet est maintenant centre sur une seule version de calcul:

- `SOLO v0 notice` (basee sur la notice SOLO 2018)

## Structure

- `app.py`: interface Streamlit unique (mode SOLO v0)
- `solo2018_rebuild/core/solo_v0_engine.py`: moteur de calcul SOLO v0
- `solo2018_rebuild/meteo/epw_reader.py`: lecture EPW et preparation meteo mensuelle

## Demarrage

```bash
streamlit run app.py
```

## Logique retenue

- Les entrees SOLO v0 sont explicites: `VECS`, `TECS`, `TEF`, `TExt`, `R global plan`.
- Les donnees EPW Nantes servent a pre-remplir les mois (`TExt`, `TEF`, `R global plan`).
- Le moteur final utilise la formulation notice avec stockage, transfert, pertes et couverture non lineaire.

## Suite

1. Caler les parametres sur tes cas SOLO de reference.
2. Valider mois par mois ecarts et conventions.
3. Stabiliser l'API d'integration Heliopilot.


