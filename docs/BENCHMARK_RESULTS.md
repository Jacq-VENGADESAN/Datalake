# Résultats du benchmark avancé

Mesure effectuée le **12 juillet 2026 à 22:01 UTC** par Jacq VENGADESAN, depuis le
client Windows vers l'API exécutée dans Docker Desktop. MinIO et PostgreSQL étaient
eux aussi conteneurisés. Chaque scénario a été répété cinq fois après échauffement ; la
médiane sert de valeur de comparaison.

| Taille du lot | `/ingest` médiane | `/ingest_fast` médiane | Gain |
|---:|---:|---:|---:|
| 1 | 58,888 ms | 56,443 ms | **4,15 %** |
| 100 | 251,508 ms | 76,681 ms | **69,51 %** |

L'objectif de 30 % est largement dépassé sur le lot de 100, régime pour lequel
l'optimisation batch a été conçue. Sur un élément, le gain reste faible : deux insertions
groupées d'une ligne ne réduisent pas le nombre d'allers-retours par rapport à deux
insertions unitaires, et NumPy ajoute un léger coût fixe.

Les temps individuels du lot de 100 sont :

- standard : 270,509 ; 251,508 ; 249,727 ; 259,330 ; 238,651 ms ;
- rapide : 60,481 ; 76,326 ; 98,683 ; 242,800 ; 76,681 ms.

La quatrième mesure rapide est un outlier visible. Le choix de la médiane empêche ce pic
ponctuel de fausser la conclusion.

Le script génère localement `benchmark-results/latest.json`. Ce fichier brut est
volontairement ignoré par Git afin d'éviter de versionner des résultats dépendants de la
machine ; les mesures de référence conservées dans le dépôt sont celles de ce document.
Le rapport JSON peut être régénéré avec :

```powershell
python scripts/benchmark.py --url http://localhost:8000 --repeats 5
```
