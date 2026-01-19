# 🃏 AI Poker Battle

**Claude Haiku 4.5 vs GPT-4o-mini** - Heads-Up No-Limit Texas Hold'em en continu 24/7

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## 🎯 Concept

Deux intelligences artificielles s'affrontent au poker Texas Hold'em en mode Heads-Up (1v1), jouant main après main sans interruption. Chaque IA analyse la situation et prend ses décisions de manière autonome via les APIs Anthropic et OpenAI.

### Caractéristiques

- ♠️ **Poker authentique** : Heads-Up No-Limit Texas Hold'em
- 🤖 **IA vs IA** : Claude Haiku 4.5 vs GPT-4o-mini
- 🔄 **Jeu continu** : Parties automatiques 24/7
- 📊 **Stats en temps réel** : Taux de victoire, biggest pot, historique
- 📱 **Responsive** : Interface adaptée mobile/desktop
- 🎲 **Betting teaser** : Section paris avec $AIWARS (à venir)

## 🏗️ Architecture

### Backend
- **Flask** : Serveur web Python
- **PyPokerEngine** : Moteur de poker complet
- **Threading** : Game loop asynchrone en arrière-plan
- **Anthropic API** : Claude Haiku 4.5 (température 1.0)
- **OpenAI API** : GPT-4o-mini (température 1.8)

### Frontend
- **HTML5 + CSS3 + Vanilla JS**
- **Dark theme** professionnel
- **Auto-refresh** toutes les 2 secondes
- **Grid layout** : Terminal / Jeu / Stats
- **Responsive** : Mobile-first avec breakpoint 768px

## 🚀 Déploiement

### Railway (Recommandé)

1. **Créer un nouveau projet Railway**
2. **Connecter le repository GitHub**
3. **Ajouter les variables d'environnement** :
   ```
   ANTHROPIC_API_KEY=your_anthropic_key
   OPENAI_API_KEY=your_openai_key
   PORT=5000
   ```
4. **Deploy automatique** : Railway détecte le Procfile et lance gunicorn

### Local

```bash
# Cloner le repo
git clone https://github.com/yourusername/ai-poker-battle.git
cd ai-poker-battle

# Créer environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows

# Installer dépendances
pip install -r requirements.txt

# Configurer variables d'environnement
export ANTHROPIC_API_KEY="your_key"
export OPENAI_API_KEY="your_key"

# Lancer l'application
python poker_battle.py
```

Accéder à : `http://localhost:5000`

## 🎮 Comment ça marche

### Game Loop

1. **Initialisation** : Chaque joueur commence avec $1000
2. **Blinds** : Small blind $5, Big blind $10
3. **Distribution** : 2 cartes privées pour chaque IA
4. **Betting rounds** :
   - **Preflop** : Les IAs décident avant les cartes communes
   - **Flop** : 3 cartes communes révélées
   - **Turn** : 4ème carte commune
   - **River** : 5ème carte commune
5. **Showdown** : Meilleure main gagne ou fold adverse
6. **Pause** : 20 secondes avant la prochaine main
7. **Reset** : Si un joueur perd tout, les stacks sont réinitialisés

### Décisions des IA

Les IA reçoivent un prompt avec :
- Leurs cartes privées
- Les cartes communes (si disponibles)
- Le montant du pot
- Leur stack actuel
- La dernière action de l'adversaire

Elles doivent répondre avec :
- `fold` : Abandonner la main
- `call` : Suivre la mise actuelle
- `raise X` : Relancer de X dollars

**Exemple de prompt** :
```
You are playing Heads-Up No-Limit Texas Hold'em poker.

Your cards: A♠ K♠
Community cards: Q♠ J♠ 2♣
Pot: $40
Your stack: $980
Opponent's last action: Raised $20

Choose your action: fold, call, or raise X
Your decision:
```

## 📊 Interface

### Desktop (3 colonnes)

```
┌─────────────┬─────────────────┬─────────────┐
│  Terminal   │   Poker Table   │    Stats    │
│   Logs      │                 │             │
│             │    Claude       │  Win Rates  │
│  Actions    │   Community     │             │
│  Events     │      GPT        │   Thoughts  │
│             │                 │             │
│             │  Betting Sec.   │             │
└─────────────┴─────────────────┴─────────────┘
```

### Mobile (vertical)

```
┌─────────────────┐
│   Poker Table   │
├─────────────────┤
│ Betting Section │
├─────────────────┤
│   Statistics    │
├─────────────────┤
│   AI Thoughts   │
└─────────────────┘
```

## 🎨 Design

- **Background** : #0d0d0d (noir profond)
- **Bordures** : #ffd700 (or) pour les éléments importants
- **Claude** : #4a9eff (bleu)
- **GPT** : #ff6b35 (orange)
- **Success** : #00ff00 (vert)
- **Police** : Courier New (monospace)
- **Cartes** : Emojis Unicode (🂡 🂮 🂷 🃅)

## 📁 Structure du Projet

```
ai-poker-battle/
├── poker_battle.py      # Backend Flask + Game loop
├── templates/
│   └── viewer.html      # Frontend interface
├── requirements.txt     # Dépendances Python
├── Procfile            # Config Railway/Heroku
├── runtime.txt         # Version Python
├── .gitignore          # Fichiers à ignorer
└── README.md           # Ce fichier
```

## 🔧 Configuration

### Variables d'environnement requises

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
PORT=5000  # Optionnel, défaut 5000
```

### Paramètres de jeu (modifiables dans `poker_battle.py`)

```python
# Stacks de départ
INITIAL_STACK = 1000

# Blinds
SMALL_BLIND = 5
BIG_BLIND = 10

# Pause entre les mains
COUNTDOWN_SECONDS = 20

# Températures des IA
CLAUDE_TEMPERATURE = 1.0
GPT_TEMPERATURE = 1.8
```

## 🐛 Dépannage

### L'IA ne répond pas
- Vérifier les clés API
- Vérifier les logs dans le terminal
- Les IAs peuvent prendre 5-10 secondes pour répondre

### Erreur PyPokerEngine
- S'assurer que PyPokerEngine 1.0.5 est installé
- Vérifier les logs pour les erreurs de game state

### Page ne se charge pas
- Vérifier que Flask tourne sur le bon port
- Vérifier les logs gunicorn (Railway)
- Essayer de redémarrer l'application

## 📈 Roadmap

- [x] ✅ Game loop fonctionnel
- [x] ✅ Intégration Claude + GPT
- [x] ✅ Interface responsive
- [x] ✅ Stats en temps réel
- [ ] 🔄 Système de betting avec $AIWARS
- [ ] 🔄 Historique des mains jouées
- [ ] 🔄 Replay des mains
- [ ] 🔄 Multi-tables (plusieurs parties en parallèle)
- [ ] 🔄 Tournois IA

## 📜 License

MIT License - Voir LICENSE pour plus de détails

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à :
- 🐛 Reporter des bugs
- 💡 Proposer des features
- 🔧 Soumettre des PRs

## 📞 Support

Pour toute question ou problème :
- Ouvrir une issue sur GitHub
- Consulter la documentation PyPokerEngine
- Vérifier les exemples dans le code

---

**Fait avec ❤️ par la communauté AI**

🃏 *May the best AI win!* 🃏
