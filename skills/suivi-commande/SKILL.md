---
name: suivi-commande
description: Expliquer au client où en est sa commande et quand il la recevra. À utiliser pour toute question « où en est ma commande ? ».
---

# Suivi de commande

1. Appelle `consulter_commande` avec le numéro donné par le client.
2. Traduis le statut en phrase simple :
   - en préparation : « elle est en cours de préparation et peut encore être annulée » ;
   - expédiée : « elle est en route, livraison sous 2 à 4 jours ouvrables » ;
   - livrée : « elle a été livrée le <date> » ;
   - retour demandé : « votre demande de retour est en cours de traitement ».
3. Si le numéro n'existe pas, demande au client de vérifier le numéro indiqué sur son e-mail de confirmation.
