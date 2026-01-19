import os
import json
import time
import random
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify
from anthropic import Anthropic
from openai import OpenAI
from pypokerengine.api.game import setup_config, start_poker
from pypokerengine.players import BasePokerPlayer
from pypokerengine.engine.card import Card

app = Flask(__name__)

# API clients
anthropic_client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Game state
game_state = {
    'hand_number': 0,
    'round': 'waiting',
    'pot': 0,
    'claude_stack': 1000,
    'gpt_stack': 1000,
    'claude_cards': [],
    'gpt_cards': [],
    'community_cards': [],
    'last_action': '',
    'winner': '',
    'countdown': 20,
    'is_playing': False,
    'claude_wins': 0,
    'gpt_wins': 0,
    'total_hands': 0,
    'biggest_pot': 0,
    'claude_current_action': '',
    'gpt_current_action': ''
}

logs = []
thoughts = []

CARD_SYMBOLS = {
    'S': '♠', 'H': '♥', 'D': '♦', 'C': '♣',
    '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
    'T': '10', 'J': 'J', 'Q': 'Q', 'K': 'K', 'A': 'A'
}

THOUGHT_TEMPLATES = {
    'claude': [
        "Analyzing pot odds...",
        "Evaluating hand strength...",
        "Calculating expected value...",
        "Considering position advantage...",
        "Reading opponent's pattern...",
        "Assessing risk/reward ratio..."
    ],
    'gpt': [
        "Reading the table...",
        "Thinking about bluff potential...",
        "Analyzing betting patterns...",
        "Considering stack sizes...",
        "Evaluating showdown value...",
        "Planning next street..."
    ]
}

def add_log(message):
    """Add a log entry with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs.append(f"[{timestamp}] {message}")
    if len(logs) > 50:
        logs.pop(0)

def add_thought(player, thought=None):
    """Add AI thought"""
    if thought is None:
        thought = random.choice(THOUGHT_TEMPLATES[player])
    thoughts.append(f"{player.upper()}: {thought}")
    if len(thoughts) > 10:
        thoughts.pop(0)

def format_card(card_str):
    """Convert card string to emoji format"""
    if not card_str or card_str == 'XX':
        return '🂠'
    rank = card_str[0]
    suit = card_str[1]
    return f"{CARD_SYMBOLS.get(rank, rank)}{CARD_SYMBOLS.get(suit, suit)}"

def parse_ai_decision(response_text):
    """Parse AI response to extract action"""
    response_text = response_text.lower().strip()
    
    if 'fold' in response_text:
        return 'fold', 0
    elif 'call' in response_text:
        return 'call', 0
    elif 'raise' in response_text or 'bet' in response_text:
        # Extract amount
        import re
        numbers = re.findall(r'\d+', response_text)
        if numbers:
            amount = int(numbers[0])
            return 'raise', amount
        return 'raise', 20  # Default raise
    else:
        # Default to call
        return 'call', 0

class AIPlayer(BasePokerPlayer):
    """Base AI player class"""
    
    def __init__(self, name, api_type):
        super().__init__()
        self.name = name
        self.api_type = api_type
        
    def declare_action(self, valid_actions, hole_card, round_state):
        """Make decision using AI API"""
        add_thought(self.name.lower())
        
        # Build prompt
        community_cards = [format_card(str(card)) for card in round_state['community_card']]
        hole_cards = [format_card(str(card)) for card in hole_card]
        
        pot = round_state['pot']['main']['amount']
        my_stack = [p['stack'] for p in round_state['seats'] if p['name'] == self.name][0]
        
        # Get last action
        action_histories = round_state.get('action_histories', {})
        last_action = "Game start"
        for street in ['preflop', 'flop', 'turn', 'river']:
            if street in action_histories and action_histories[street]:
                last = action_histories[street][-1]
                last_action = f"{last['action']} {last.get('amount', '')}"
        
        prompt = f"""You are playing Heads-Up No-Limit Texas Hold'em poker.

Your cards: {' '.join(hole_cards)}
Community cards: {' '.join(community_cards) if community_cards else 'None yet'}
Pot: ${pot}
Your stack: ${my_stack}
Opponent's last action: {last_action}

Valid actions: {', '.join([a['action'] for a in valid_actions])}

Choose your action. Reply with ONLY one of:
- "fold" (give up hand)
- "call" (match current bet)
- "raise X" (where X is your raise amount, min 20, max your stack)

Your decision:"""

        try:
            if self.api_type == 'claude':
                response = anthropic_client.messages.create(
                    model="claude-haiku-4-20250122",
                    max_tokens=100,
                    temperature=1.0,
                    messages=[{"role": "user", "content": prompt}]
                )
                decision_text = response.content[0].text
            else:  # GPT
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=100,
                    temperature=1.8,
                    messages=[{"role": "user", "content": prompt}]
                )
                decision_text = response.choices[0].message.content
            
            action_type, amount = parse_ai_decision(decision_text)
            
            # Find matching valid action
            for action in valid_actions:
                if action['action'] == action_type:
                    if action_type == 'raise':
                        # Clamp amount to valid range
                        min_amount = action['amount'].get('min', 20)
                        max_amount = action['amount'].get('max', my_stack)
                        amount = max(min_amount, min(amount, max_amount))
                        add_log(f"{self.name} raises ${amount}")
                        return action_type, amount
                    else:
                        add_log(f"{self.name} {action_type}s")
                        return action_type, action['amount']
            
            # Default to call if available, else fold
            if any(a['action'] == 'call' for a in valid_actions):
                add_log(f"{self.name} calls")
                return 'call', 0
            else:
                add_log(f"{self.name} folds")
                return 'fold', 0
                
        except Exception as e:
            add_log(f"ERROR {self.name}: {str(e)}")
            # Default to fold on error
            return 'fold', 0
    
    def receive_game_start_message(self, game_info):
        pass
    
    def receive_round_start_message(self, round_count, hole_card, seats):
        pass
    
    def receive_street_start_message(self, street, round_state):
        pass
    
    def receive_game_update_message(self, action, round_state):
        pass
    
    def receive_round_result_message(self, winners, hand_info, round_state):
        pass

def play_poker_hand():
    """Play one hand of poker"""
    global game_state
    
    game_state['hand_number'] += 1
    game_state['total_hands'] += 1
    game_state['round'] = 'preflop'
    game_state['winner'] = ''
    game_state['last_action'] = ''
    
    add_log(f"=== HAND #{game_state['hand_number']} ===")
    
    # Setup game config
    config = setup_config(
        max_round=1,
        initial_stack=game_state['claude_stack'],
        small_blind_amount=5
    )
    
    claude_player = AIPlayer("Claude", "claude")
    gpt_player = AIPlayer("GPT", "gpt")
    
    config.register_player(name="Claude", algorithm=claude_player)
    config.register_player(name="GPT", algorithm=gpt_player)
    
    # Start game
    try:
        game_result = start_poker(config, verbose=0)
        
        # Extract results
        for player_info in game_result['players']:
            if player_info['name'] == 'Claude':
                game_state['claude_stack'] = player_info['stack']
            elif player_info['name'] == 'GPT':
                game_state['gpt_stack'] = player_info['stack']
        
        # Determine winner
        if game_state['claude_stack'] > game_state['gpt_stack']:
            game_state['winner'] = 'Claude'
            game_state['claude_wins'] += 1
        else:
            game_state['winner'] = 'GPT'
            game_state['gpt_wins'] += 1
        
        add_log(f"🏆 {game_state['winner']} wins the hand!")
        
        # Check if game is over (one player busted)
        if game_state['claude_stack'] <= 0 or game_state['gpt_stack'] <= 0:
            add_log("=== GAME OVER - RESETTING STACKS ===")
            game_state['claude_stack'] = 1000
            game_state['gpt_stack'] = 1000
        
    except Exception as e:
        add_log(f"ERROR in hand: {str(e)}")
        game_state['round'] = 'error'

def game_loop():
    """Main game loop running in background"""
    global game_state
    
    while True:
        try:
            if not game_state['is_playing']:
                time.sleep(1)
                continue
            
            # Countdown phase
            game_state['round'] = 'countdown'
            for i in range(20, 0, -1):
                game_state['countdown'] = i
                time.sleep(1)
            
            # Play hand
            game_state['countdown'] = 0
            play_poker_hand()
            
        except Exception as e:
            add_log(f"FATAL ERROR: {str(e)}")
            time.sleep(5)

@app.route('/')
def index():
    return render_template('viewer.html')

@app.route('/api/state')
def get_state():
    """Return current game state"""
    return jsonify({
        'game_state': game_state,
        'logs': logs[-20:],  # Last 20 logs
        'thoughts': thoughts[-5:]  # Last 5 thoughts
    })

@app.route('/api/start')
def start_game():
    """Start the game loop"""
    game_state['is_playing'] = True
    add_log("🎮 Game started!")
    return jsonify({'status': 'started'})

@app.route('/api/stop')
def stop_game():
    """Stop the game loop"""
    game_state['is_playing'] = False
    add_log("⏸️ Game paused")
    return jsonify({'status': 'stopped'})

if __name__ == '__main__':
    # Start game loop in background thread
    game_thread = threading.Thread(target=game_loop, daemon=True)
    game_thread.start()
    
    # Auto-start game
    game_state['is_playing'] = True
    add_log("🎮 AI Poker Battle initialized!")
    
    # Run Flask app
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
