# Packaging HelioStock

Avant de livrer une archive HelioStock :

- ne pas inclure `__pycache__/` ;
- ne pas inclure `.pytest_cache/` ;
- ne pas inclure un ancien projet imbriqué `heliostock_module/heliostock_module/` ;
- vérifier qu'un seul package `heliostock/` est présent dans l'archive ;
- vérifier qu'un seul fichier principal `test_engine_smoke.py` est présent, sauf séparation volontaire des tests.

Commande de contrôle utile :

```powershell
Get-ChildItem -Recurse -Directory -Filter __pycache__
Get-ChildItem -Recurse -Directory -Filter .pytest_cache
Get-ChildItem -Recurse -Directory -Filter heliostock_module
```

