---
name: retour-produit
description: Traiter une demande de retour ou un produit défectueux, de la vérification jusqu'à creer_retour. À utiliser dès qu'un client veut retourner un produit.
---

# Retour d'un produit

1. Appelle `consulter_commande` : le statut doit être « livrée ». Note le nombre de jours depuis la livraison.
2. Appelle `chercher_politique` avec « retour » pour relire la règle en vigueur.
3. Décide :
   - délai respecté → appelle `creer_retour` ;
   - délai dépassé → n'appelle pas `creer_retour`, explique la règle avec le nombre de jours.
4. Rédige le motif de `creer_retour` ainsi : `<catégorie> : <détail du client>`,
   avec la catégorie `défectueux`, `erreur de commande` ou `ne convient pas`.
   Exemple : `défectueux : la souris ne s'allume pas`.
5. Pour un produit défectueux, précise au client qu'il peut choisir un échange ou un remboursement.
