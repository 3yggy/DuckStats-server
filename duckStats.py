from flask import Flask, request, render_template, redirect, abort
from flask_sqlalchemy import SQLAlchemy
import urllib.request, random, re, string, json, datetime
from urllib.parse import urlencode
from sqlalchemy import JSON, desc, or_
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import Float, DateTime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os

steamApiKey = os.environ.get('STEAM_API_KEY')
adress = 'http://127.0.0.1:5000/' if __name__ == '__main__' else 'http://duck-stats.herokuapp.com/' 
print('running on: '+adress)

#spared: after trickshots before coolnes
templateStats = ['kills', 'suicides', 'timesKilled', 'matchesWon', 'trophiesSinceLastWinCounter', 'trophiesSinceLastWin', 'timesSpawned', 'trophiesWon', 'gamesPlayed', 'fallDeaths', 'timesSwore', 'bulletsFired', 'bulletsThatHit', 'trickShots', 'coolness', 'unarmedDucksShot', 'killsFromTheGrave', 'timesNetted', 'timeInNet', 'loyalFans', 'unloyalFans', 'timeUnderMindControl', 'timesMindControlled', 'timeOnFire', 'timesLitOnFire', 'airTime', 'timesJumped', 'disarms', 'timesDisarmed', 'quacks', 'timeWithMouthOpen', 'timeSpentOnMines', 'minesSteppedOn', 'timeSpentReloadingOldTimeyWeapons', 'presentsOpened', 'respectGivenToDead', 'funeralsPerformed', 'funeralsRecieved', 'timePreaching', 'conversions', 'timesConverted','lastPlayed', 'lastWon', 'lastKillTime']

app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
db = SQLAlchemy(app)

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["300 per day", "70 per hour"]
)

class Duck(db.Model):
    __tablename__ = 'ducks'
    steam_id = db.Column(db.BigInteger,primary_key = True, unique = True, nullable = False)
    steam_name = db.Column(db.String(64),unique = False, nullable = True)
    real_name = db.Column(db.String(64),unique = False, nullable = True)
    stats = db.Column(postgresql.JSON,unique = False, nullable = True)
    auth = db.Column(db.String(16),unique = False, nullable = True)
    updated = db.Column(db.DateTime ,default = datetime.datetime.now)

class Authentification(db.Model):
    pin = db.Column(db.String, primary_key=True)
    auth = db.Column(db.String(16),unique = False, nullable = False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# 1- success
# 0 - wrong code
# 2 - invalid json
# 3 - invalid duck

bans = os.environ.get('BANS_LIST').split('|')
@app.before_request
def limit_remote_addr():
    if request.headers.getlist("X-Forwarded-For"):
        ip = request.headers.getlist("X-Forwarded-For")[0]
    else:
        ip = request.remote_addr
    if str(ip) in bans:
        abort(403)
    else:
        print('connection: '+ip)

@app.route('/',methods=['POST','GET'])
def Home():
    if request.method== 'POST':
        pass
    if request.method== 'GET':
        return render_template('home.html')

@app.route('/upload/<int:steam_id>',methods=['post'])
def Submit(steam_id):
    duck = GetDuck(steam_id)
    auth = request.form.get('auth')

    if duck is None:
        return '3 - invalid duck'
    elif duck.auth and duck.auth == auth:
        _json = request.form.get('json')
        if _json:
            stats = json.loads(_json)

            if len(stats) - len(templateStats) > 5:
                print(f'too long: {len(templateStats)} != {len(stats)}')
                for stat in stats:
                    print (stat)

                return '2 - invalid stats; too long'

            i = 0
            for stat in stats:
                templateStat = templateStats[i]
                i += 1
                if not stat in templateStats or len(str(stats[stat])) > 125:
                    print(f'{stat} is bad {len(str(stats[stat]))}')
                    return '2 - invalid stats; weird stats'

            duck.stats = stats
            duck.updated = datetime.datetime.now()
            db.session.commit()
            return "1 - success"
        else:
            return '2 - invalid stats'
        
    else:
        return f'0 - invalid auth: ({steam_id},{auth})'
        pass

@app.route('/auth/<string:pin>')
def AuthenticateMe(pin):

    DropAuth(pin)

    responseURL = adress+'/validate/'+pin

    args = urlencode(
        {
			'openid.ns':'http://specs.openid.net/auth/2.0',
			'openid.mode': 'checkid_setup',
			'openid.return_to': responseURL, 
			'openid.realm': responseURL, 
			'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select', 
			'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select'
		}
    )
    resp = redirect(f'https://steamcommunity.com/openid/login?'+args)

    return resp

@app.route('/pickup/<string:pin>')
def PickUp(pin):
    
    auth = GetAuth(pin)
    if auth:
        DropAuth(pin)
        _return = auth.auth
    else:
        _return = '6 invalid pin'
    delete_expired()
    return _return

@app.route('/validate/<string:pin>')
def Validate(pin):
    results = request.values
    validationResponse ={
			'openid.assoc_handle': results['openid.assoc_handle'],
			'openid.signed': results['openid.signed'],
			'openid.sig' : results['openid.sig'],
			'openid.ns': results ['openid.ns']
		}

    sign = results['openid.signed'].split(',')
    for item in sign:
        openIDItem = 'openid.{0}'.format(item)
        if results[openIDItem] not in validationResponse:
            validationResponse[openIDItem] = results[openIDItem]

    validationResponse['openid.mode'] = 'check_authentication'
    cleanResponse = urlencode(validationResponse).encode("utf-8")

    with urllib.request.urlopen('https://steamcommunity.com/openid/login/',cleanResponse) as f:
        yeild = f.read().decode('utf-8')

    steamId = results['openid.claimed_id'].partition('https://steamcommunity.com/openid/id/')[2]

    SetAuth(steamId,''.join(random.choice(string.ascii_letters) for i in range(16)))

    entryDuck = GetDuck(steamId)

    if 'is_valid:true' in yeild and entryDuck:

        AddAuth(pin,entryDuck.auth)
    
        return 'YOU MAY RETURN TO DUCK GAME'
    else:
        return steamId if entryDuck else 'entry duck invalid :('

@app.route('/stats/<int:steam_id>')
def Stats(steam_id):
    duck = GetDuck(steam_id)
    if duck:
        if(duck.stats):
            return str(duck.stats)
        else:
            return '8, no stats on this duck'
    else:
        return '8, No stats for this duck :('

@app.route('/stats')
def ClientView():
    
    args = request.args.to_dict()

    if not 'page' in args:
        args['page'] = 1

    if not 'sort' in args or not args['sort'] in templateStats:
        args['sort'] = 'updated'

    page = int(args['page'])

    sort = args['sort']

    q = Duck.query

    if 'search' in args and args['search'].strip():
        search = args['search'].strip()

        if search.isdigit() and len(search) == 17:
            order = q.filter(Duck.steam_id == int(search))
        else:
            order = q.filter(or_(Duck.steam_name.ilike('%'+search+'%'),Duck.real_name.ilike('%'+search+'%')))
    else:
        byUpdate = sort.lower() == 'updated'

        if byUpdate:
            oq = Duck.updated
        else:
            if sort[:4].lower() != 'last':
                oq = Duck.stats[sort].astext.cast(Float) 
            else:
                oq = Duck.stats[sort].astext.cast(DateTime)

        if not ('desc' in args and args['desc']):
            oq = desc(oq)

        order =q.order_by(oq)

    order = order.filter(Duck.stats != None)
    pag = order.paginate(page=page, per_page=16)
    ducks = pag.items
    
    nijjaVals = {
        'template' : templateStats,
        'request' : args,
        'info' : 'by ziggy',
        'Ducks' : [],
        'pag' : pag
        }

    for duck in ducks:

        steamDucks = json.loads(urllib.request.urlopen('https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key='+steamApiKey+'&steamids='+str(duck.steam_id)).read())['response']['players']

        if len(steamDucks) > 0:
            nijjaVals['Ducks'].append({
                'vals' : duck,
                'steam' : steamDucks[0]
            })

    return render_template('viewer.html', **nijjaVals)

def GetAuth(pin):
    return Authentification.query.filter_by(pin=pin).first()

def DropAuth(pin):
    auth = GetAuth(pin)
    if(auth):
        db.session.delete(auth)
        db.session.commit()

def AddAuth(pin,auth):
    DropAuth(pin)
    auth = Authentification(pin=pin,auth=auth)
    db.session.add(auth)
    db.session.commit()

def delete_expired():
    limit = datetime.datetime.now() - datetime.timedelta(minutes=8)
    Authentification.query.filter_by(timestamp = limit).delete()
    db.session.commit()

def GetDuck(steam_id):
    return Duck.query.filter_by(steam_id=steam_id).first()

def SetAuth(steam_id, auth):

    duck = GetDuck(steam_id)
    if not duck:
        names = json.loads(urllib.request.urlopen('https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key='+steamApiKey+'&steamids='+str(duck.steam_id)).read())['response']['players']
        if names and 'personaname' in names[0]:
            duck_ = names[0]
            pname = duck_['personaname']
            duck = Duck(steam_id = steam_id)
            duck.steam_name = pname
            if 'realname' in duck_:
                duck.real_name = duck_['realname']
            else:
                duck.real_name = pname
        else:
            print(f'ERROR: {steam_id} is invalid')
            return

        print(f'added {duck.steam_name}')

    duck.auth = auth

    db.session.add(duck)
    db.session.commit()

    print(f'{duck.steam_id} auth set to {duck.auth}')

db.create_all()
db.session.commit()

if __name__ == '__main__':
    app.run(debug = True)