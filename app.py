from pokebase import cache
cache.set_cache('pokeapi_cache')
from flask import Flask, render_template, request, jsonify
import requests.exceptions
import random
import math
import pokebase as pb

app = Flask(__name__)

# main page
@app.route("/")
def index():
    # generate a random pokemon and its corresponding sprite.
    def get_random_pkmn():
        rand_id = random.randint(1, 1026)
        poke = pb.pokemon(rand_id)
        sprite = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{rand_id}.png"
        return poke.name, sprite

    # both the user and the opponent receive a random pokemon to battle with
    user_name, user_sprite = get_random_pkmn()
    opponent_name, opponent_sprite = get_random_pkmn()
    
    # using the names, fetch the data (stats, moves, etc) for the battling pokemon
    user_pokemon = Pokemon(user_name).to_dict()
    opponent_pokemon = Opponent_Pokemon(opponent_name).to_dict()
    
    # add the sprites to the dictionary
    user_pokemon['sprite'] = user_sprite
    opponent_pokemon['sprite'] = opponent_sprite

    # render the html for the main page, and pass on the dictionaries containing the pokemon info
    return render_template('index.html', user_pokemon=user_pokemon, opponent_pokemon=opponent_pokemon)

# processes 1 turn, in which each pokemon attacks once.
# returns the results of the turn, including whether a pokemon is fainted, and their new HP after taking damage.
@app.route("/attack", methods=['POST'])
def execute_turn():
    data = request.get_json() # extract the turn data from the site/frontend, and turn it into a dictionary
    #print("received data:", data)  for debugging purposes
    user_name = data.get('user_pokemon')
    opponent_name = data.get('opponent_pokemon')
    your_move = data.get('your_move')
    
    if not user_name or not opponent_name or not your_move:
        return jsonify({'error': 'missing user/opponent name, or your move'}), 400

    user_data = Pokemon(user_name) # data.get('user_pokemon') just returns the name. this gets the actual data
    opponent_data = Opponent_Pokemon(opponent_name)
    # the opponent uses a different class as they'll have a move hardcoded rather than a random selection of moves.
    # this is just to make loading faster, you could definitely change this code to give opponent real moves that they randomly select.
    your_move_data = Move(your_move)
    
    user_current_hp = data.get('user_hp')
    user_data.current_hp = user_current_hp
    opponent_current_hp = data.get('opponent_hp')
    opponent_data.current_hp = opponent_current_hp
    
    if not opponent_data.moves:
        return jsonify({'error': 'Opponent has no valid moves'}), 400
    opponent_move_data = Move('tackle')

    first_fainted = False
    second_fainted = False
    
    if not all([user_data, opponent_data, your_move_data, opponent_move_data]):
        return jsonify({'error': 'Missing required data'}), 400
    
    # speed determines who attacks first. a pokemon with higher speed will move first.
    if user_data.stats['speed'] >= opponent_data.stats['speed']:
    # If it's a speedtie, you will go first.
        first = user_data
        first_move = your_move_data
        second = opponent_data
        second_move = opponent_move_data
    elif user_data.stats['speed'] < opponent_data.stats['speed']:
        first = opponent_data
        first_move = opponent_move_data
        second = user_data
        second_move = your_move_data

    first_dmg_dealt = calculate_damage_raw(first, second, first_move) 
    if (second.current_hp - first_dmg_dealt) <= 0:
        second.current_hp = 0 # avoid negative HP values
        second_fainted = True
    else:
        second.current_hp = (second.current_hp - first_dmg_dealt)
        
    # place the results of the first attack into a dict
    result = {
        'first_damage_dealt': first_dmg_dealt,
        'first_move_name': first_move.name,
        'second_hp': second.current_hp,
        'second_fainted': second_fainted,
        'first_message': f"{first.name} used {first_move.name}!"
    }
    
    # if the first attack knocks out the target, the opponent won't move.
    # if the target survives, they will attack back.
    if not second_fainted: 
        second_dmg_dealt = calculate_damage_raw(second, first, second_move)
        if (first.current_hp - second_dmg_dealt) <= 0:
            first.current_hp = 0
            first_fainted = True
        else:
            first.current_hp = first.current_hp - second_dmg_dealt
        result.update({ # update the dict to have results from the second attack
            'second_damage_dealt': second_dmg_dealt,
            'second_move_name': second_move.name,
            'first_hp': first.current_hp,
            'first_fainted': first_fainted,
            'second_message': f"{second.name} used {second_move.name}!"
        })
    return jsonify(result) #jsonify to make it accessible to the frontend

# fetch info for a Pokemon
class Pokemon:
    pokemon_cache = {}
    
    def __init__(self, name):
        self.name = name
        self.types = []
        self.stats = {}
        self.current_hp = 0
        self.moves = []
        if name in self.pokemon_cache:
            cached = self.pokemon_cache[name] # Use cached info if possible
            self.name = cached['name']
            self.types = cached['types']
            self.stats = cached['stats']
            self.moves = cached['moves']
            self.current_hp = self.stats['hp'] 
            return
        try:
            self.poke = pb.pokemon(name.lower().replace(' ', '-'))
        except Exception as e:
            print(f"[ERROR] Failed to load Pokémon '{name}': {e}")
            return
                
        try:
            self.name = self.poke.name.lower().replace(' ', '-')
            self.types = [t.type.name for t in self.poke.types]
            self.stats = {s.stat.name: s.base_stat for s in self.poke.stats}
            # convert base stats into actual stat numbers
            for stat in self.stats:
                if stat == 'hp':
                    self.stats[stat] = (((2 * self.stats[stat] + 31) * 100)/100) + 100 + 10
                                            #    Assumed Level 100      ^           ^
                else:                       #                           v
                    self.stats[stat] = (((2 * self.stats[stat] + 31) * 100)/100) + 5
            self.current_hp = self.stats['hp']
    
            # for simplicity, non-damaging moves will be excluded. there's way too many to implement
            # in a reasonable amount of time.
            
            self.moves = []
            # fetch the pokemon's moveset
            response = requests.get(f'https://pokeapi.co/api/v2/pokemon/{name}') # request data about the pokemon
            if response.status_code == 200:
                data = response.json()
            moves_to_check = random.sample(data['moves'], min(8, len(data['moves']))) # check up to 8 moves to see if they are damaging.
            damaging_moves = self.get_damaging_moves(moves_to_check)                                               
            self.moves = damaging_moves if len(damaging_moves) <= 4 else random.sample(damaging_moves, 4) # if there are more than 4 damaging moves found, use 4 of them.
            
            self.pokemon_cache[name] = {
                'name': self.name,
                'types': self.types,
                'stats': self.stats,
                'moves': self.moves
            }
        except Exception as e:
            print(f"[ERROR] Failed to Load {e}")
            return
        
    # convert the data into a dictionary so that the HTML side can understand it
    def to_dict(self):
        return {
            "name": self.name,
            "types": self.types,
            "stats": self.stats,
            "current_hp": self.current_hp,
            "moves": [move.name for move in self.moves],
        }
            
    def get_damaging_moves(self, movepool):
        damaging_moves = []
        for move in movepool:
            move_info = Move(move['move']['name']) # get info about each move
            if move_info.power is not None and move_info.damage_class !='status': # if it deals damage directly
                damaging_moves.append(move_info)
        return damaging_moves

# seperate class for opponent pokemon to reduce move API calls
# opponent pokemon will only have one predetermined move.
# This can be changed to give them a true moveset, but this improves load times.
class Opponent_Pokemon:
    pokemon_cache = {}
    
    def __init__(self, name):
        self.name = name
        self.types = []
        self.stats = {}
        self.current_hp = 0
        self.moves = []
        if name in self.pokemon_cache:
            self.poke = self.pokemon_cache[name]
        else:
            try:
                self.poke = pb.pokemon(name.lower().replace(' ', '-'))
                self.pokemon_cache[name] = self.poke
            except Exception as e:
                print(f"[ERROR] Failed to load Pokémon '{name}': {e}")
                return
                
        try:
            self.name = self.poke.name.lower().replace(' ', '-')
            self.types = [t.type.name for t in self.poke.types]
            self.stats = {s.stat.name: s.base_stat for s in self.poke.stats}
            self.moves = ['tackle']
            # convert base stats into actual stat numbers
            for stat in self.stats:
                if stat == 'hp':
                    self.stats[stat] = (((2 * self.stats[stat] + 31) * 100)/100) + 100 + 10
                                            #    Assumed Level 100      ^           ^
                else:                       #                           v
                    self.stats[stat] = (((2 * self.stats[stat] + 31) * 100)/100) + 5
            self.current_hp = self.stats['hp']
        except Exception as e:
            print(f"[ERROR] Failed to Load {e}")
            return

    def to_dict(self):
        return {
            "name": self.name,
            "types": self.types,
            "stats": self.stats,
            "current_hp": self.current_hp,
            "moves": self.moves,
        }
    
# fetch data of a move
class Move:
    move_cache = {}
    def __init__(self, name):
        if name in self.move_cache:
            move_data = self.move_cache[name] # use cached data if possible
        else:
            try:
                move_data = pb.move(name)
                self.move_cache[name] = move_data
            except Exception as e:
                print(f"[ERROR] Failed to load Move '{name}': {e}")
                move_data = None

        if move_data: # if the move exists in the database
            self.name = move_data.name
            self.type = move_data.type.name
            self.power = move_data.power or 0
            self.damage_class = move_data.damage_class.name
        else: # if not, uses a placeholder move
            self.name = name
            self.type = "normal"
            self.power = 0
            self.damage_class = "unknown"
                        
# find how effective a move is against the opposing pokemon, and apply a corresponding damage multiplier.
# i could've used pokebase to more elegantly do this but I wanted to reduce API calls since loading is slow as it is
def get_type_effectiveness(move_type, defender_typing):
    type_chart = {
        'normal':    {'rock': 0.5, 'ghost': 0.0, 'steel': 0.5},
        'fire':      {'fire': 0.5, 'water': 0.5, 'grass': 2.0, 'ice': 2.0, 'bug': 2.0, 'rock': 0.5, 'dragon': 0.5, 'steel': 2.0},
        'water':     {'fire': 2.0, 'water': 0.5, 'grass': 0.5, 'ground': 2.0, 'rock': 2.0, 'dragon': 0.5},
        'electric':  {'water': 2.0, 'electric': 0.5, 'grass': 0.5, 'ground': 0.0, 'flying': 2.0, 'dragon': 0.5},
        'grass':     {'fire': 0.5, 'water': 2.0, 'grass': 0.5, 'poison': 0.5, 'ground': 2.0, 'flying': 0.5, 'bug': 0.5, 'rock': 2.0, 'dragon': 0.5, 'steel': 0.5},
        'ice':       {'fire': 0.5, 'water': 0.5, 'grass': 2.0, 'ice': 0.5, 'ground': 2.0, 'flying': 2.0, 'dragon': 2.0, 'steel': 0.5},
        'fighting':  {'normal': 2.0, 'ice': 2.0, 'rock': 2.0, 'dark': 2.0, 'steel': 2.0, 'poison': 0.5, 'flying': 0.5, 'psychic': 0.5, 'bug': 0.5, 'ghost': 0.0, 'fairy': 0.5},
        'poison':    {'grass': 2.0, 'poison': 0.5, 'ground': 0.5, 'rock': 0.5, 'ghost': 0.5, 'steel': 0.0, 'fairy': 2.0},
        'ground':    {'fire': 2.0, 'electric': 2.0, 'grass': 0.5, 'poison': 2.0, 'flying': 0.0, 'bug': 0.5, 'rock': 2.0, 'steel': 2.0},
        'flying':    {'electric': 0.5, 'grass': 2.0, 'fighting': 2.0, 'bug': 2.0, 'rock': 0.5, 'steel': 0.5},
        'psychic':   {'fighting': 2.0, 'poison': 2.0, 'psychic': 0.5, 'dark': 0.0, 'steel': 0.5},
        'bug':       {'fire': 0.5, 'grass': 2.0, 'fighting': 0.5, 'poison': 0.5, 'flying': 0.5, 'psychic': 2.0, 'ghost': 0.5, 'dark': 2.0, 'steel': 0.5, 'fairy': 0.5},
        'rock':      {'fire': 2.0, 'ice': 2.0, 'fighting': 0.5, 'ground': 0.5, 'flying': 2.0, 'bug': 2.0, 'steel': 0.5},
        'ghost':     {'normal': 0.0, 'psychic': 2.0, 'ghost': 2.0, 'dark': 0.5},
        'dragon':    {'dragon': 2.0, 'steel': 0.5, 'fairy': 0.0},
        'dark':      {'fighting': 0.5, 'psychic': 2.0, 'ghost': 2.0, 'dark': 0.5, 'fairy': 0.5},
        'steel':     {'fire': 0.5, 'water': 0.5, 'electric': 0.5, 'ice': 2.0, 'rock': 2.0, 'fairy': 2.0, 'steel': 0.5},
       }
    multiplier = 1.0
    for typ in defender_typing:
        multiplier *= type_chart.get(move_type, {}).get(typ, 1.0)
    return multiplier    

# calculate damage dealt by a move
def calculate_damage_raw(attacker, defender, move, level=100):
    if move.power == 0:
        return 0
    A = attacker.stats['attack'] if move.damage_class == 'physical' else attacker.stats['special-attack'] # special category attacks deal damage based on opponent's Special Defense
    D = defender.stats['defense'] if move.damage_class == 'physical' else defender.stats['special-defense'] # physical category attacks deal damage based on opponent's Defense
    basedmg = (((2 * level / 5 + 2) * move.power * A / D) / 50) + 2 # damage formula
    stab = 1.5 if move.type in attacker.types else 1.0 # Same Type Attack Bonus increases the power of an attack by 1.5x if the move type matches the user
    type_effectiveness = get_type_effectiveness(move.type, defender.types) 
    critical = 1.5 if random.random() < 0.0625 else 1.0 # 1.5x damage critical hit 1/16 of the time
    dmg_range = random.uniform(0.85, 1.0) # pokemon damage has a inherent randomness

    modifier = stab * type_effectiveness * critical * dmg_range
    return math.floor(basedmg * modifier)

# run the app
if __name__ == "__main__":
    app.run(debug=True)
