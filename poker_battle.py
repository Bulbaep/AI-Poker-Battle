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
    'street': 'waiting',  # preflop, flop, turn, river
    'pot': 0,
    'claude_stack': 1000,
    'gpt_stack': 1000,
    'claude_cards': [],
    'gpt_cards': [],
    'community_cards': [],
    'last_action': '',
    'winner': '',
    'countdown': 60,
    'hand_countdown': 0,  # Timer between hands (10 seconds)
    'is_playing': False,
    'wait_for_new_game': False,  # True after a bust, triggers 60s countdown
    'claude_wins': 0,  # Hands won (intermediate stat, resets each game)
    'gpt_wins': 0,  # Hands won (intermediate stat, resets each game)
    'claude_games_won': 0,  # GAMES won (bust opponent)
    'gpt_games_won': 0,  # GAMES won (bust opponent)
    'total_hands': 0,
    'biggest_pot': 0,
    'claude_current_action': '',
    'gpt_current_action': '',
    'action_history': [],  # For displaying recent actions
    'claude_win_probability': 0,
    'gpt_win_probability': 0,
    'claude_is_thinking': False,
    'gpt_is_thinking': False,
    'stack_history': [],  # For stack graph (last 10 hands)
    
    # Gameplay stats
    'total_allins': 0,  # Total all-ins in current game
    'game_pots': [],  # List of pot sizes in current game for calculating avg
    'current_game_hands': 0,  # Hands in current game
    'longest_game': 0,  # Longest game in hands
    'shortest_game': 0,  # Shortest game in hands
    'hand_history': [],  # For hand history panel (last 5 hands)
    'claude_streak': 0,  # Consecutive wins
    'gpt_streak': 0,  # Consecutive wins
    'winning_hand_info': '',  # Detailed winner info
    'dealer': 'claude'  # Who is dealer/button (alternates each hand)
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
    if len(logs) > 200:  # Keep more logs for larger terminal
        logs.pop(0)

def add_thought(player, thought=None):
    """Add AI thought"""
    if thought is None:
        thought = random.choice(THOUGHT_TEMPLATES[player])
    thoughts.append(f"{player.upper()}: {thought}")
    if len(thoughts) > 20:
        thoughts.pop(0)

def format_card(card_str):
    """Convert card string to emoji format"""
    if not card_str or card_str == 'XX':
        return '🂠'
    rank = card_str[0]
    suit = card_str[1]
    return f"{CARD_SYMBOLS.get(rank, rank)}{CARD_SYMBOLS.get(suit, suit)}"

def get_hand_rank_name(rank):
    """Convert hand rank number to readable name"""
    # PyPokerEngine returns bit-based scores
    # The higher bits represent the hand type
    # We extract the most significant bits to determine hand type
    
    # Hand type thresholds (approximate based on PyPokerEngine scoring)
    if rank >= 8000000:
        return "Straight Flush"
    elif rank >= 7000000:
        return "Four of a Kind"
    elif rank >= 6000000:
        return "Full House"
    elif rank >= 5000000:
        return "Flush"
    elif rank >= 4000000:
        return "Straight"
    elif rank >= 3000000:
        return "Three of a Kind"
    elif rank >= 2000000:
        return "Two Pair"
    elif rank >= 1000000:
        return "One Pair"
    else:
        return "High Card"


def calculate_win_probabilities(claude_cards, gpt_cards, community_cards):
    """Calculate win probabilities using Monte Carlo simulation with PyPokerEngine"""
    try:
        from pypokerengine.engine.hand_evaluator import HandEvaluator
        from pypokerengine.engine.card import Card
        
        # If no cards yet, return 50/50
        if not claude_cards or not gpt_cards:
            return 50.0, 50.0
        
        # Convert card symbols to PyPokerEngine Card objects
        def card_to_pypoker_obj(card_str):
            if not card_str or '🂠' in card_str:
                return None
            
            # Map symbols to PyPokerEngine format
            rank_map = {'A': 'A', 'K': 'K', 'Q': 'Q', 'J': 'J', '10': 'T',
                       '9': '9', '8': '8', '7': '7', '6': '6', '5': '5',
                       '4': '4', '3': '3', '2': '2'}
            suit_map = {'♠': 'S', '♥': 'H', '♦': 'D', '♣': 'C'}
            
            # Extract rank and suit from card string
            for rank, code in rank_map.items():
                if rank in card_str:
                    for suit, suit_code in suit_map.items():
                        if suit in card_str:
                            # Create Card object from string like "SA", "HK", etc.
                            return Card.from_str(suit_code + code)
            return None
        
        # Convert all cards to Card objects
        claude_hole = [card_to_pypoker_obj(c) for c in claude_cards]
        gpt_hole = [card_to_pypoker_obj(c) for c in gpt_cards]
        board = [card_to_pypoker_obj(c) for c in community_cards]
        
        # Remove None values
        claude_hole = [c for c in claude_hole if c]
        gpt_hole = [c for c in gpt_hole if c]
        board = [c for c in board if c]
        
        # Need exactly 2 hole cards each
        if len(claude_hole) != 2 or len(gpt_hole) != 2:
            return 50.0, 50.0
        
        # Build remaining deck (as Card objects)
        all_cards_52 = []
        for suit in ['S', 'H', 'D', 'C']:
            for rank in ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']:
                all_cards_52.append(Card.from_str(suit + rank))
        
        # Remove known cards (compare as strings for easier matching)
        used_cards_str = set([str(c) for c in (claude_hole + gpt_hole + board)])
        deck = [c for c in all_cards_52 if str(c) not in used_cards_str]
        
        # Determine how many community cards to deal
        cards_needed = 5 - len(board)
        
        if cards_needed == 0:
            # All 5 community cards revealed - just evaluate
            claude_strength = HandEvaluator.eval_hand(claude_hole, board)
            gpt_strength = HandEvaluator.eval_hand(gpt_hole, board)
            
            if claude_strength > gpt_strength:
                return 100.0, 0.0
            elif gpt_strength > claude_strength:
                return 0.0, 100.0
            else:
                return 50.0, 50.0
        
        # Monte Carlo simulation
        simulations = 500
        claude_wins = 0
        gpt_wins = 0
        ties = 0
        
        for _ in range(simulations):
            # Deal random remaining community cards
            remaining_community = random.sample(deck, cards_needed)
            full_board = board + remaining_community
            
            # Evaluate both hands
            claude_strength = HandEvaluator.eval_hand(claude_hole, full_board)
            gpt_strength = HandEvaluator.eval_hand(gpt_hole, full_board)
            
            if claude_strength > gpt_strength:
                claude_wins += 1
            elif gpt_strength > claude_strength:
                gpt_wins += 1
            else:
                ties += 1
        
        # Calculate percentages
        total = simulations
        claude_percentage = ((claude_wins + ties * 0.5) / total) * 100.0
        gpt_percentage = ((gpt_wins + ties * 0.5) / total) * 100.0
        
        return round(claude_percentage, 1), round(gpt_percentage, 1)
        
    except Exception as e:
        # Silently return 50/50 on error (don't spam logs)
        return 50.0, 50.0

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
        global game_state
        
        # Set thinking state for this player
        if self.name == 'Claude':
            game_state['claude_is_thinking'] = True
            game_state['claude_current_action'] = ''
        else:
            game_state['gpt_is_thinking'] = True
            game_state['gpt_current_action'] = ''
        
        # Wait 5 seconds while "thinking"
        time.sleep(5)
        
        # Clear thinking state
        if self.name == 'Claude':
            game_state['claude_is_thinking'] = False
        else:
            game_state['gpt_is_thinking'] = False
        
        add_thought(self.name.lower())
        
        # Build prompt
        community_cards = [format_card(str(card)) for card in round_state['community_card']]
        hole_cards = [format_card(str(card)) for card in hole_card]
        
        # Update game state with cards (for display to viewers, not other AI)
        if self.name == 'Claude':
            game_state['claude_cards'] = hole_cards
        else:
            game_state['gpt_cards'] = hole_cards
        
        # Update community cards and street
        game_state['community_cards'] = community_cards
        game_state['pot'] = round_state['pot']['main']['amount']
        
        # Determine current street
        num_community = len(community_cards)
        if num_community == 0:
            game_state['street'] = 'preflop'
        elif num_community == 3:
            game_state['street'] = 'flop'
        elif num_community == 4:
            game_state['street'] = 'turn'
        elif num_community == 5:
            game_state['street'] = 'river'
        
        # Calculate win probabilities
        claude_prob, gpt_prob = calculate_win_probabilities(
            game_state['claude_cards'],
            game_state['gpt_cards'],
            game_state['community_cards']
        )
        game_state['claude_win_probability'] = claude_prob
        game_state['gpt_win_probability'] = gpt_prob
        
        pot = round_state['pot']['main']['amount']
        my_stack = [p['stack'] for p in round_state['seats'] if p['name'] == self.name][0]
        
        # Get last action
        action_histories = round_state.get('action_histories', {})
        last_action = "Game start"
        for street in ['preflop', 'flop', 'turn', 'river']:
            if street in action_histories and action_histories[street]:
                last = action_histories[street][-1]
                last_action = f"{last['action']} {last.get('amount', '')}"
        
        # Add occasional bluff opportunity (10% chance)
        import random
        bluff_mode = random.random() < 0.1
        
        # Aggressive mode when short stack
        is_short_stack = my_stack <= 500
        
        prompt = f"""You are playing Heads-Up No-Limit Texas Hold'em poker.

YOUR SITUATION:
Your cards: {' '.join(hole_cards)}
Community cards: {' '.join(community_cards) if community_cards else 'None yet (preflop)'}
Pot: ${pot}
Your stack: ${my_stack}
Opponent's last action: {last_action}

{"⚠️ SHORT STACK ALERT! ⚠️" if is_short_stack else ""}
{"You have ≤$500 remaining. Time to get AGGRESSIVE!" if is_short_stack else ""}

POKER STRATEGY GUIDELINES:
1. With WEAK starting hands (7-2, 9-3, J-4, etc.), you should usually FOLD after the flop if you don't hit at least a pair
2. {"ALL-IN OR FOLD! Don't raise small amounts - either shove all-in with decent hands or fold. Hands worth shoving: Any pair, AK, AQ, AJ, AT, KQ, KJ, suited connectors 8-9 or better" if is_short_stack else "Be AGGRESSIVE! Consider raising 50-150% of the pot with strong hands (any pair, AK, AQ, KQ, suited connectors). You can raise up to your entire stack if you feel confident. Big raises get big folds!"}
3. {"Push aggressively - you need to double up or die trying!" if is_short_stack else "Don't be afraid to apply pressure - poker rewards aggression"}
4. {"Consider shoving preflop with medium pairs or high cards - you can't wait!" if is_short_stack else "Build the pot with your strong hands - don't slowplay too much"}
5. {"You feel confident today - consider a BLUFF this hand!" if bluff_mode else "Play aggressive and confident poker"}

Valid actions: {', '.join([a['action'] for a in valid_actions])}

Choose your action. Reply with ONLY one of:
- "fold" (give up hand)
- "call" (match current bet)
- "raise X" (where X is your raise amount, min 20, max your stack)

Your decision:"""

        try:
            if self.api_type == 'claude':
                response = anthropic_client.messages.create(
                    model="claude-3-haiku-20240307",
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
                        min_amount = max(20, action['amount'].get('min', 20))  # Ensure min is at least 20
                        max_amount = action['amount'].get('max', my_stack)
                        
                        # Validate and clamp amount
                        if amount < min_amount:
                            amount = min_amount
                        if amount > max_amount:
                            amount = max_amount
                        
                        # Final safety check - ensure amount is positive
                        if amount < 0:
                            add_log(f"⚠️ {self.name} tried invalid raise ${amount}, defaulting to call")
                            return 'call', 0
                        
                        # Detect all-in
                        is_allin = (amount >= my_stack * 0.95)  # Consider 95%+ of stack as all-in
                        if is_allin:
                            game_state['total_allins'] += 1
                            add_log(f"{self.name} goes ALL-IN ${amount}! 🔥")
                            game_state['action_history'].insert(0, f"{self.name} ALL-IN ${amount}! 🔥")
                        else:
                            add_log(f"{self.name} raises ${amount}")
                            game_state['action_history'].insert(0, f"{self.name} raises ${amount}")
                        
                        if len(game_state['action_history']) > 10:
                            game_state['action_history'].pop()
                        
                        # Set current action for visual display
                        if self.name == 'Claude':
                            game_state['claude_current_action'] = f"ALL-IN ${amount}" if is_allin else f"RAISE ${amount}"
                        else:
                            game_state['gpt_current_action'] = f"ALL-IN ${amount}" if is_allin else f"RAISE ${amount}"
                        
                        return action_type, amount
                    else:
                        add_log(f"{self.name} {action_type}s")
                        game_state['action_history'].insert(0, f"{self.name} {action_type}s")
                        if len(game_state['action_history']) > 10:
                            game_state['action_history'].pop()
                        
                        # Set current action for visual display
                        action_display = action_type.upper()
                        if self.name == 'Claude':
                            game_state['claude_current_action'] = action_display
                        else:
                            game_state['gpt_current_action'] = action_display
                        
                        return action_type, action['amount']
            
            # Default to call if available, else fold
            if any(a['action'] == 'call' for a in valid_actions):
                add_log(f"{self.name} calls")
                game_state['action_history'].insert(0, f"{self.name} calls")
                if len(game_state['action_history']) > 10:
                    game_state['action_history'].pop()
                
                if self.name == 'Claude':
                    game_state['claude_current_action'] = "CALL"
                else:
                    game_state['gpt_current_action'] = "CALL"
                
                return 'call', 0
            else:
                add_log(f"{self.name} folds")
                game_state['action_history'].insert(0, f"{self.name} folds")
                if len(game_state['action_history']) > 10:
                    game_state['action_history'].pop()
                
                if self.name == 'Claude':
                    game_state['claude_current_action'] = "FOLD"
                else:
                    game_state['gpt_current_action'] = "FOLD"
                
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
    game_state['current_game_hands'] += 1  # Track hands in current game
    game_state['round'] = 'preflop'
    game_state['street'] = 'preflop'
    game_state['winner'] = ''
    game_state['last_action'] = ''
    
    # Reset cards for new hand
    game_state['claude_cards'] = []
    game_state['gpt_cards'] = []
    game_state['community_cards'] = []
    game_state['pot'] = 0
    game_state['action_history'] = []
    game_state['claude_current_action'] = ''
    game_state['gpt_current_action'] = ''
    game_state['claude_win_probability'] = 50.0
    game_state['gpt_win_probability'] = 50.0
    game_state['claude_is_thinking'] = False
    game_state['gpt_is_thinking'] = False
    
    add_log(f"=== HAND #{game_state['hand_number']} ===")
    
    # Alternate dealer each hand
    game_state['dealer'] = 'gpt' if game_state['dealer'] == 'claude' else 'claude'
    add_log(f"🔘 Dealer: {game_state['dealer'].upper()} (pays SB: $5)")
    
    # Alert if any player is in short stack aggressive mode
    if game_state['claude_stack'] <= 500:
        add_log(f"⚠️ CLAUDE in AGGRESSIVE MODE! (${game_state['claude_stack']} ≤ $500)")
    if game_state['gpt_stack'] <= 500:
        add_log(f"⚠️ GPT in AGGRESSIVE MODE! (${game_state['gpt_stack']} ≤ $500)")
    
    # Clear winner banner for new hand
    game_state['winning_hand_info'] = ''
    
    # Calculate progressive blinds (increase every 10 hands)
    blind_level = game_state['hand_number'] // 10
    small_blind = 5 + (blind_level * 5)  # 5, 10, 15, 20, 25...
    big_blind = small_blind * 2
    
    add_log(f"💰 Blinds: ${small_blind}/${big_blind} (Level {blind_level + 1})")
    
    # Check if either player is busted (can't afford big blind)
    if game_state['claude_stack'] < big_blind:
        add_log(f"💀 CLAUDE IS BUSTED! (${game_state['claude_stack']} < ${big_blind} blind)")
        game_state['claude_stack'] = 0
        game_state['gpt_games_won'] += 1
        add_log("🏆🏆🏆 GPT WINS THE GAME! CLAUDE IS BUSTED! 🏆🏆🏆")
        
        # Track game length for stats
        if game_state['current_game_hands'] > 0:
            if game_state['longest_game'] == 0 or game_state['current_game_hands'] > game_state['longest_game']:
                game_state['longest_game'] = game_state['current_game_hands']
            if game_state['shortest_game'] == 0 or game_state['current_game_hands'] < game_state['shortest_game']:
                game_state['shortest_game'] = game_state['current_game_hands']
        
        # Reset for new game
        add_log("=== NEW GAME STARTING IN 60 SECONDS ===")
        add_log("💰 PLACE YOUR BETS NOW!")
        game_state['claude_stack'] = 1000
        game_state['gpt_stack'] = 1000
        game_state['claude_wins'] = 0
        game_state['gpt_wins'] = 0
        game_state['hand_history'] = []
        game_state['stack_history'] = []
        game_state['biggest_pot'] = 0
        game_state['wait_for_new_game'] = True
        game_state['total_allins'] = 0
        game_state['game_pots'] = []
        game_state['current_game_hands'] = 0
        return
    
    if game_state['gpt_stack'] < big_blind:
        add_log(f"💀 GPT IS BUSTED! (${game_state['gpt_stack']} < ${big_blind} blind)")
        game_state['gpt_stack'] = 0
        game_state['claude_games_won'] += 1
        add_log("🏆🏆🏆 CLAUDE WINS THE GAME! GPT IS BUSTED! 🏆🏆🏆")
        
        # Track game length for stats
        if game_state['current_game_hands'] > 0:
            if game_state['longest_game'] == 0 or game_state['current_game_hands'] > game_state['longest_game']:
                game_state['longest_game'] = game_state['current_game_hands']
            if game_state['shortest_game'] == 0 or game_state['current_game_hands'] < game_state['shortest_game']:
                game_state['shortest_game'] = game_state['current_game_hands']
        
        # Reset for new game
        add_log("=== NEW GAME STARTING IN 60 SECONDS ===")
        add_log("💰 PLACE YOUR BETS NOW!")
        game_state['claude_stack'] = 1000
        game_state['gpt_stack'] = 1000
        game_state['claude_wins'] = 0
        game_state['gpt_wins'] = 0
        game_state['hand_history'] = []
        game_state['stack_history'] = []
        game_state['biggest_pot'] = 0
        game_state['wait_for_new_game'] = True
        game_state['total_allins'] = 0
        game_state['game_pots'] = []
        game_state['current_game_hands'] = 0
        return
    
    # CRITICAL FIX: Use minimum stack to avoid money creation
    # PyPokerEngine gives same initial_stack to all players
    min_stack = min(game_state['claude_stack'], game_state['gpt_stack'])
    
    # Setup game config with progressive blinds
    config = setup_config(
        max_round=1,
        initial_stack=min_stack,
        small_blind_amount=small_blind
    )
    
    claude_player = AIPlayer("Claude", "claude")
    gpt_player = AIPlayer("GPT", "gpt")
    
    config.register_player(name="Claude", algorithm=claude_player)
    config.register_player(name="GPT", algorithm=gpt_player)
    
    # Start game
    try:
        game_result = start_poker(config, verbose=0)
        
        # Calculate stack differences before the hand
        claude_excess = game_state['claude_stack'] - min_stack
        gpt_excess = game_state['gpt_stack'] - min_stack
        
        # Extract results and restore excess chips
        for player_info in game_result['players']:
            if player_info['name'] == 'Claude':
                game_state['claude_stack'] = player_info['stack'] + claude_excess
            elif player_info['name'] == 'GPT':
                game_state['gpt_stack'] = player_info['stack'] + gpt_excess
        
        # Verify total is still $2000
        total = game_state['claude_stack'] + game_state['gpt_stack']
        if abs(total - 2000) > 1:  # Allow 1$ rounding error
            add_log(f"⚠️ WARNING: Total chips = ${total} (should be $2000)")
        
        # Update biggest pot and track pots for average
        if game_state['pot'] > game_state['biggest_pot']:
            game_state['biggest_pot'] = game_state['pot']
        
        # Track pot for average calculation
        if game_state['pot'] > 0:
            game_state['game_pots'].append(game_state['pot'])
        
        # Evaluate hands if we have all cards
        winning_hand_detail = "High Card"  # Default value
        if game_state['claude_cards'] and game_state['gpt_cards'] and game_state['community_cards']:
            try:
                from pypokerengine.engine.hand_evaluator import HandEvaluator
                from pypokerengine.engine.card import Card
                
                # Convert cards to Card objects
                def to_card_obj(card_str):
                    rank_map = {'A': 'A', 'K': 'K', 'Q': 'Q', 'J': 'J', '10': 'T',
                               '9': '9', '8': '8', '7': '7', '6': '6', '5': '5',
                               '4': '4', '3': '3', '2': '2'}
                    suit_map = {'♠': 'S', '♥': 'H', '♦': 'D', '♣': 'C'}
                    for rank, code in rank_map.items():
                        if rank in card_str:
                            for suit, suit_code in suit_map.items():
                                if suit in card_str:
                                    return Card.from_str(suit_code + code)
                    return None
                
                claude_hole = [to_card_obj(c) for c in game_state['claude_cards'] if to_card_obj(c)]
                gpt_hole = [to_card_obj(c) for c in game_state['gpt_cards'] if to_card_obj(c)]
                board = [to_card_obj(c) for c in game_state['community_cards'] if to_card_obj(c)]
                
                if len(claude_hole) == 2 and len(gpt_hole) == 2 and len(board) >= 3:
                    claude_rank = HandEvaluator.eval_hand(claude_hole, board)
                    gpt_rank = HandEvaluator.eval_hand(gpt_hole, board)
                    
                    add_log(f"   Claude rank: {claude_rank}, GPT rank: {gpt_rank}")  # Debug log
                    
                    claude_hand_name = get_hand_rank_name(claude_rank)
                    gpt_hand_name = get_hand_rank_name(gpt_rank)
                    
                    if claude_rank > gpt_rank:
                        winning_hand_detail = f"{claude_hand_name} beats {gpt_hand_name}"
                    elif gpt_rank > claude_rank:
                        winning_hand_detail = f"{gpt_hand_name} beats {claude_hand_name}"
                    else:
                        winning_hand_detail = f"Tie with {claude_hand_name}"
                else:
                    # Not enough cards, probably fold
                    winning_hand_detail = "by fold or insufficient cards"
            except Exception as e:
                add_log(f"Error evaluating hands: {e}")
                winning_hand_detail = "by stack comparison"
        
        # Determine winner and update streaks
        if game_state['claude_stack'] > game_state['gpt_stack']:
            game_state['winner'] = 'Claude'
            game_state['claude_wins'] += 1
            game_state['claude_streak'] += 1
            game_state['gpt_streak'] = 0
        else:
            game_state['winner'] = 'GPT'
            game_state['gpt_wins'] += 1
            game_state['gpt_streak'] += 1
            game_state['claude_streak'] = 0
        
        # Store winning hand info with actual cards
        claude_cards_str = ''.join(game_state['claude_cards']) if game_state['claude_cards'] else '??'
        gpt_cards_str = ''.join(game_state['gpt_cards']) if game_state['gpt_cards'] else '??'
        
        game_state['winning_hand_info'] = f"🏆 {game_state['winner'].upper()} WINS! • {claude_cards_str} vs {gpt_cards_str} • Pot: ${game_state['pot']}"
        
        add_log(f"🏆 {game_state['winner']} wins the hand!")
        add_log(f"   Claude: {claude_cards_str} vs GPT: {gpt_cards_str}")
        if winning_hand_detail:
            add_log(f"   {winning_hand_detail}")
        
        game_state['last_action'] = f"Winner: {game_state['winner']}!"
        
        # Add to hand history (keep last 5)
        hand_record = {
            'hand_number': game_state['hand_number'],
            'winner': game_state['winner'],
            'pot': game_state['pot'],
            'hand_detail': winning_hand_detail,
            'claude_cards': game_state['claude_cards'].copy(),
            'gpt_cards': game_state['gpt_cards'].copy(),
            'community_cards': game_state['community_cards'].copy()
        }
        game_state['hand_history'].insert(0, hand_record)
        if len(game_state['hand_history']) > 5:
            game_state['hand_history'].pop()
        
        # Add to stack history (keep last 10 data points)
        game_state['stack_history'].append({
            'hand': game_state['hand_number'],
            'claude': game_state['claude_stack'],
            'gpt': game_state['gpt_stack']
        })
        if len(game_state['stack_history']) > 10:
            game_state['stack_history'].pop(0)
        
        # Check if game is over (one player busted)
        if game_state['claude_stack'] <= 0 or game_state['gpt_stack'] <= 0:
            # Determine who won the GAME (not just the hand)
            if game_state['claude_stack'] > 0:
                game_state['claude_games_won'] += 1
                add_log("🏆🏆🏆 CLAUDE WINS THE GAME! GPT IS BUSTED! 🏆🏆🏆")
            else:
                game_state['gpt_games_won'] += 1
                add_log("🏆🏆🏆 GPT WINS THE GAME! CLAUDE IS BUSTED! 🏆🏆🏆")
            
            # Track game length for stats
            if game_state['current_game_hands'] > 0:
                if game_state['longest_game'] == 0 or game_state['current_game_hands'] > game_state['longest_game']:
                    game_state['longest_game'] = game_state['current_game_hands']
                if game_state['shortest_game'] == 0 or game_state['current_game_hands'] < game_state['shortest_game']:
                    game_state['shortest_game'] = game_state['current_game_hands']
            
            # Reset for new game
            add_log("=== NEW GAME STARTING IN 60 SECONDS ===")
            add_log("💰 PLACE YOUR BETS NOW!")
            game_state['claude_stack'] = 1000
            game_state['gpt_stack'] = 1000
            game_state['claude_streak'] = 0
            game_state['gpt_streak'] = 0
            game_state['claude_wins'] = 0  # Reset hands won counter
            game_state['gpt_wins'] = 0  # Reset hands won counter
            game_state['hand_history'] = []
            game_state['stack_history'] = []
            game_state['biggest_pot'] = 0
            game_state['wait_for_new_game'] = True  # Trigger 60s countdown
            
            # Reset gameplay stats for new game
            game_state['total_allins'] = 0
            game_state['game_pots'] = []
            game_state['current_game_hands'] = 0
        
    except Exception as e:
        import traceback
        error_msg = f"ERROR in hand: {type(e).__name__}: {str(e)}"
        add_log(error_msg)
        add_log(f"Traceback: {traceback.format_exc()[:500]}")  # First 500 chars
        game_state['round'] = 'error'

def game_loop():
    """Main game loop running in background"""
    global game_state
    
    while True:
        try:
            if not game_state['is_playing']:
                time.sleep(1)
                continue
            
            # Countdown phase (only after a bust/new game)
            if game_state['wait_for_new_game']:
                game_state['round'] = 'countdown'
                add_log("⏰ 60 second countdown for betting!")
                for i in range(60, 0, -1):
                    game_state['countdown'] = i
                    time.sleep(1)
                game_state['wait_for_new_game'] = False
                add_log("🎮 NEW GAME STARTING NOW!")
            
            # Play hand
            game_state['countdown'] = 0
            play_poker_hand()
            
            # 10 second pause between hands (for readability)
            game_state['round'] = 'hand_pause'
            for i in range(10, 0, -1):
                game_state['hand_countdown'] = i
                time.sleep(1)
            game_state['hand_countdown'] = 0
            
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
        'logs': logs[-100:],  # Last 100 logs to fill the terminal
        'thoughts': thoughts[-15:]  # Last 15 thoughts to fill the section
    })

@app.route('/api/start')
def start_game():
    """Start the game loop"""
    game_state['is_playing'] = True
    game_state['wait_for_new_game'] = True  # Trigger initial 60s countdown
    add_log("🎮 Game started! Place your bets!")
    return jsonify({'status': 'started'})

@app.route('/api/stop')
def stop_game():
    """Stop the game loop"""
    game_state['is_playing'] = False
    add_log("⏸️ Game paused")
    return jsonify({'status': 'stopped'})

# Start game loop in background thread (must be outside if __name__ for gunicorn)
game_thread = threading.Thread(target=game_loop, daemon=True)
game_thread.start()

# Auto-start game
game_state['is_playing'] = True
game_state['wait_for_new_game'] = True  # Trigger initial countdown
add_log("🎮 AI Poker Battle initialized!")

if __name__ == '__main__':
    # Run Flask app (only used for local development)
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
