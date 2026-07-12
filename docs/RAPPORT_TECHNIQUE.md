# Rapport technique — VelibPulse Data Lake

**Étudiant : Jacq VENGADESAN**  
**Classe : BDML2**  
**Module : Data Lakes & Data Integration — EFREI 2025-2026**  
**Enseignant : Yvann VINCENT**

## Introduction

Trouver un Vélib' ou rendre son vélo dépend de deux ressources opposées : un vélo
disponible au départ et une bornette libre à l'arrivée. Une station presque vide et une
station presque pleine posent donc toutes les deux un problème, mais pas au même usager.
VelibPulse construit un historique exploitable de cette tension opérationnelle.

La question traitée est la suivante : **comment absorber un référentiel fichier et un
flux temps réel hétérogènes, conserver leur preuve brute, puis fournir des alertes simples
et explicables par une interface unique ?**

## Sources

La première source est un export CSV de la Ville de Paris. Il fournit le code, le nom, la
capacité et les coordonnées des stations. Le dépôt en contient un extrait versionné de
dix lignes afin que le build soit déterministe et ne dépende pas d'un téléchargement au
premier lancement.

La seconde source est le flux public `station_status.json` de Vélib' Métropole. Il est
sans clé, au format GBFS et évolue en continu. Chaque station expose les compteurs de
vélos mécaniques, électriques et de bornettes ainsi que son état opérationnel.

Ces deux sources ont une clé de rapprochement commune : `stationCode` dans le JSON et
`stationcode` dans le CSV.

## Architecture réalisée

La zone raw est un bucket MinIO. Le pipeline y écrit les octets exacts reçus sous une clé
horodatée. Les fichiers ne sont pas écrasés : toute transformation peut être rejouée et
auditée.

La zone staging est le schéma PostgreSQL du même nom. Le référentiel y est mis à jour
par upsert. Les instantanés sont normalisés et dédupliqués par station, timestamp et
source.

La zone curated contient les KPI. Le taux de disponibilité mesure la part de vélos parmi
les emplacements observés. Le score de pression vaut zéro à l'équilibre et un à un
extrême vide/plein. La classification distingue pénurie de vélos, pénurie de bornes et
indisponibilité technique. Cette règle déterministe a été préférée à un modèle de Machine
Learning : avec un unique instantané au démarrage, un modèle prédictif donnerait une
apparence scientifique sans base temporelle suffisante.

FastAPI expose ensuite les trois zones. Les lectures sont paginées et filtrables.
`/health` teste réellement MinIO et PostgreSQL. `/stats` reste utilisable en cas de panne
partielle et expose l'erreur du service concerné.

## Orchestration

Le DAG Airflow s'exécute toutes les cinq minutes. Il initialise les ressources, charge le
référentiel de manière idempotente, collecte le flux GBFS et transmet par XCom la clé de
l'objet raw à la transformation. Deux nouvelles tentatives espacées d'une minute
absorbent les erreurs réseau transitoires. Une seule instance du DAG peut être active à
la fois.

Airflow a été retenu plutôt que DVC parce que la principale source est un flux temporel.
La planification et l'historique des exécutions sont ici plus importants que le
versionnement d'un dataset statique.

## Niveau avancé

`POST /ingest` et `POST /ingest_fast` acceptent exactement le même schéma et produisent
les mêmes KPI. La première route est une baseline honnête : calcul et insertion ligne par
ligne. La seconde applique les notions du cours d'optimisation : vectorisation NumPy,
masques booléens et insertions groupées.

Pour un lot de cent éléments, la baseline effectue jusqu'à deux cents ordres SQL contre
deux pour la route rapide. Pour un seul élément, le coût fixe de la vectorisation peut
annuler le gain. C'est pourquoi le script fourni mesure séparément les lots de 1 et 100,
répète chaque scénario cinq fois et compare les médianes. La mesure réalisée sous Docker
le 12 juillet 2026 donne **251,508 ms contre 76,681 ms** sur cent éléments, soit un gain
médian de **69,51 %**. Sur un élément, le gain est seulement de 4,15 %, ce qui confirme
que l'optimisation vise les lots. Les résultats individuels et la méthode sont consignés
dans `docs/BENCHMARK_RESULTS.md`.

## Validation

La suite automatisée couvre :

- lecture du CSV et refus de coordonnées invalides ;
- variantes du schéma GBFS ;
- égalité fonctionnelle des versions naïve et vectorisée ;
- classification vide, pleine, équilibrée et hors ligne ;
- validation de l'API et limites de pagination ;
- comportement dégradé des endpoints de supervision.

Les commandes de test et de lint sont documentées dans le README.

## Limites et évolutions

Le jeu CSV versionné est un extrait. Les stations non présentes sont tout de même
traitées, mais sans nom ni coordonnées officiels. L'export complet peut le remplacer sans
modification du code.

Le score de pression décrit l'état présent ; il ne prédit pas la disponibilité future.
Après plusieurs semaines de collecte, une évolution pertinente serait un modèle par
station et créneau horaire, évalué contre une baseline saisonnière. L'historique pourrait
aussi être partitionné et exposé dans un tableau de bord cartographique.

## Conclusion

VelibPulse répond à l'ensemble des exigences standard et implémente le niveau avancé.
Le projet privilégie la reproductibilité, l'idempotence et l'explicabilité. Son principal
enseignement est architectural : la zone raw permet de corriger ou d'améliorer les
transformations futures sans perdre la donnée originale, tandis que la séparation des
fonctions pures et des adaptateurs de stockage rend le système testable et évolutif.
