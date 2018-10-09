 # Copyright 2018 Cedric Mesnil <cslashm@gmail.com>, Ledger SAS
 #
 # Licensed under the Apache License, Version 2.0 (the 'License');
 # you may not use this file except in compliance with the License.
 # You may obtain a copy of the License at
 #
 #     http://www.apache.org/licenses/LICENSE-2.0
 #
 # Unless required by applicable law or agreed to in writing, software
 # distributed under the License is distributed on an 'AS IS' BASIS,
 # WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 # See the License for the specific language governing permissions and
 # limitations under the License.


import sys
import unicodedata
import readline
import binascii
from struct import pack
import hashlib
import hmac

from ecpy import curves
from Cryptodome.Hash import keccak

from ledgerblue.comm import getDongle

from .dictionaries.languages import monero_langs


# =========================================================================================
#                                            MISC
# =========================================================================================

MAJOR = 0
MINOR = 8

def usage():
    print('''
Usage:
    python -m ledger.monero.seedconv online|offline

    online:  Seed will be avalaible on the NanoS screen. It is possible to clear it directly from the device.
    offline: Seed is computed offline (NanoS is not required) from your 24 BIPS32 words
    ''')

def banner():
    print('''
=============================================================
TurtleCoin Seed Converter v%s.%s. Copyright (c) Ledger SAS 20018.
Licensed under the Apache License, Version 2.0
=============================================================
 
        '''%(MAJOR,MINOR))

def printdbg(*args):
    print(*args)
    return

def error(msg):
    print ('Ooops: %s'%msg)
    print ('Aborting, sorry.')
    sys.exit(1)

def NKFDbytes(str):
    return  unicodedata.normalize('NFKD', str).encode()

def retrieve_language():
    print('* Select Language')
    i = 0
    dflt = -1
    for l in monero_langs:
        if len(l['words']) != 1626:
            print('Wrong dictionary length : %d. 1626 expected. Dictionary %s (%s) skipped.'
                  %(len(l['words']), l['language_name'], l['english_language_name']))
        print('  %2d : %s (%s)'%(i, l['language_name'], l['english_language_name']))
        if  l['english_language_name'] == 'English':
            dflt = i
        i += 1
    n = input('Enter the number corresponding to the language of your choice (%d): '%dflt)
    if len(n) == 0:
        n = dflt
    return monero_langs[int(n)]


# =========================================================================================
#                                          OFFLINE
# =========================================================================================

def retrieve_credentials():
    print()
    print("WARNING: Be sure to use a TRUSTED and SAFE computer.")
    w = input('* Continue? (yes/no): ')
    if w != "yes":
        print ('Aborting.')
        sys.exit(1)

    print()
    w = input('* Enter your NanoS 12/18/24 words: ')
    w = w.split()
    if len(w) not in (12,24,18):
        error('Your mnemonic does not contain 12, 18 or 24 words, but %d'%len(w))
    w = ' '.join(w)

    print()
    p = input('* Enter your NanoS passphrase (may be empty): ')

    return w,p


def mnemonic_to_seed(mnemonic, passphrase=''):    
    seed = hashlib.pbkdf2_hmac('sha512', NKFDbytes(mnemonic), NKFDbytes(u'mnemonic'+passphrase), 2048)
    return seed


def seed_to_master_key(seed):
    ''' return (mkey, mchain) '''
    I = hmac.new(NKFDbytes(u'Bitcoin seed'), seed, 'sha512' ).digest()
    return I[0:32], I[32:]

def master_key_to_child_key(key,path):
    G = curves.Curve.get_curve('secp256k1').generator
    O = curves.Curve.get_curve('secp256k1').order
    path = path.split('/')
    kpar = key[0]
    cpar = key[1]
    assert path[0] == 'm'
    for child in path[1:]:
        hardened = child[len(child)-1]=="'"

        printdbg('\nprocess %s'%child)
        printdbg('kpar %s'%binascii.hexlify(kpar))
        printdbg('cpar %s'%binascii.hexlify(cpar))
        printdbg('hardened %d'%hardened)


        if hardened:
            child  = int(child[:len(child)-1])
            child += 0x80000000 
            data = b'\x00'+kpar+child.to_bytes(4,'big')
        else:
            child  = int(child)
            k = int.from_bytes(kpar,'big')
            kG = k*G
            Wpar = kG.x.to_bytes(32,'big')
            if kG.y&1 == 0:
                Wpar = b'\x02' + Wpar
            else:
                Wpar = b'\x03' + Wpar
            data = Wpar+int(child).to_bytes(4,'big')

        printdbg('hmac key: %s'%binascii.hexlify(cpar))
        printdbg('hmac input: %s'%binascii.hexlify(data))
        I = hmac.new(cpar, data, 'sha512').digest()
        printdbg('hmac output: %s'%binascii.hexlify(I))

        Il, Ir = I[:32], I[32:]
        Il = int.from_bytes(Il,'big')
        kpar = int.from_bytes(kpar,'big')
        Il = (Il +kpar) % O
        Il = Il.to_bytes(32,'big')
        kpar,cpar = Il,Ir
        printdbg('ki %s'%binascii.hexlify(kpar))
        printdbg('ci %s'%binascii.hexlify(cpar))

    printdbg()
    return kpar,cpar


def turtlecoin_seed_to_turtlecoin_keys(seed):
  l = 0x1000000000000000000000000000000014def9dea2f79cd65812631a5cf5d3ed
  printdbg('turtlecoin_seed_to_turtlecoin_keys: seed %s'%seed.hex())
  kh = keccak.new(digest_bits=256)
  kh.update(seed)
  b = kh.digest()  
  printdbg('turtlecoin_seed_to_turtlecoin_keys: b %s'%b.hex())
  ble = int.from_bytes(b,'little')%l
  b = ble.to_bytes(32, 'little')

  kh = keccak.new(digest_bits=256)
  kh.update(b)
  a = kh.digest()
  ale = int.from_bytes(a,'little')%l
  a = ale.to_bytes(32, 'little')
  printdbg('turtlecoin_seed_to_turtlecoin_keys: a %s'%a.hex())

  return a,b


def spendkey_to_words(seed, language):
    if (len(seed) %4) != 0 or len(seed) == 0:
        return None

    # 4 bytes -> 3 words.  8 digits base 16 -> 3 digits base 1626
    unique_prefix_length = language['prefix_length']
    word_list = language['words']
    word_list_length = len(word_list)
    words_store = []
    for i in range(0, len(seed)//4):
        val = (seed[i*4+0]<<0) | (seed[i*4+1]<<8) | (seed[i*4+2]<<16) | (seed[i*4+3]<<24)

        w1 = val % word_list_length;
        w2 = ((val // word_list_length) + w1) % word_list_length;
        w3 = (((val // word_list_length) // word_list_length) + w2) % word_list_length;

        words_store.append(word_list[w1]);
        words_store.append(word_list[w2]);
        words_store.append(word_list[w3]);
    
    trimmed_words = u''
    for w in words_store:
        trimmed_words += w[0:unique_prefix_length]
    checksum = binascii.crc32(trimmed_words.encode('utf8'))
    checksum = checksum % 24
    words_store.append(words_store[checksum])

    return words_store



def convert_mnemonic(language, ledger_mnemonic, passphrase):
    s = mnemonic_to_seed(ledger_mnemonic, passphrase)
    mkey = seed_to_master_key(s)
    turtlecoin_ki, turtlecoin_ci = master_key_to_child_key(mkey, u"m/44'/1984'/0'/0/0")
    turtlecoin_seed = turtlecoin_ki
    turtlecoin_view_key, turtlecoin_spend_key = turtlecoin_seed_to_turtlecoin_keys(turtlecoin_seed)
    turtlecoin_words = spendkey_to_words(turtlecoin_spend_key, language)

    printdbg('seed: %s'%binascii.hexlify(s))
    printdbg('Km : %s'%binascii.hexlify(mkey[0]))
    printdbg('Cm:  %s'%binascii.hexlify(mkey[0]))
    printdbg('turtlecoin_seed: %s'%binascii.hexlify(turtlecoin_seed))
    printdbg('turtlecoin view  keys: %s'%binascii.hexlify(turtlecoin_view_key))
    printdbg('turtlecoin spend keys: %s'%binascii.hexlify(turtlecoin_spend_key))
    printdbg('turtlecoin words: %d %s'%(len(turtlecoin_words), ' '.join(turtlecoin_words)))

    return turtlecoin_words, turtlecoin_view_key, turtlecoin_spend_key, turtlecoin_seed




def get_offline_seed(lang):
    mnemonic, passphrase = retrieve_credentials()
    electrum_words,  turtlecoin_view_key, turtlecoin_spend_key, turtlecoin_seed = convert_mnemonic(lang, mnemonic, passphrase)
    print(u'''
    * Result:
      ---------------------------------------------------------------------------------------------------
      | TurtleCoin Electrum words :  {0:<70} |
      |                          {1:<70} |
      |                          {2:<70} |
      |                                                                                                 |
      | seed                  :  {3:<70} |
      | Spend key             :  {4:<70} |
      | View key              :  {5:<70} |
      ---------------------------------------------------------------------------------------------------
    ''' .format (' '.join(electrum_words[0:8]),' '.join(electrum_words[8:16]),' '.join(electrum_words[16:]),
            binascii.hexlify(turtlecoin_seed).decode(),
            binascii.hexlify(turtlecoin_spend_key).decode(),
            binascii.hexlify(turtlecoin_view_key).decode()))


# =========================================================================================
#                                          ONLINE                                         
# =========================================================================================

def send_dict_chunk(dongle, p2, chunk,start,cnt):
    header = pack('>4B', 0x00, 0x28, 0x01, p2)
    data = pack('>BII', 0,start,cnt) + chunk
    apdu = header+pack('>B',len(data))+data
    print('.', end='')
    dongle.exchange(apdu)
    print('.', end='')

def get_online_seed(lang):
    if lang['english_language_name'] not in ("English", "Esperanto", "French", "Italian", "Lobjan", "Portuguese"):
        error("%s not supported online"%lang['english_language_name'])

    print("Open device...")
    dongle = getDongle(False)
 
    print("Erase old key words...")
    dongle.exchange(pack('>6B', 0x00, 0x28, 0x02, 0x00, 0x01, 0x00))

    print("Load dictionnary", end='')
    start = 0
    cnt = 0
    chunk = b''
    for w in lang['words']:
        w = w.encode('ascii')
        if 1+8+len(chunk)+1+len(w) > 254:

            send_dict_chunk(dongle, 0, chunk, start, cnt)
            start += cnt
            cnt = 0;
            chunk = b''        
        chunk += pack('>b', len(w))+w
        cnt += 1;
    send_dict_chunk(dongle,lang['prefix_length'], chunk, start, cnt)
    print()
    print("Done.")

def clear_online_seed(lang):
    print("Open device...")
    dongle = getDongle(False)
 
    print("Erase old key words...")
    dongle.exchange(pack('>6B', 0x00, 0x28, 0x02, 0x00, 0x01, 0x00))


# =========================================================================================
#                                          MAIN                                         
# =========================================================================================
def test():
    # Ledger: abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about
    # TurtleCoin: dice fixate eluded idled friendly argue tuition token guest bawled atrium eight gone laboratory
    # intended lukewarm nifty damp unquoted mighty inorganic nucleus gills huts dice
    # seed  CFDF58139A7EAA375FA4CB38122D6C548A25E37B783724F47265C662CD6545BD
    # spend CB0B04F3F4F3B6C09498397E79E92C2B5A3C2DF3E4C6C29A20D83CE2C2DB8F0F
    # view  D1117D49402940ABC14C40EEAA30112057D464783B24DFF46D9B2242ADFF160E
    turtlecoin_view_key, turtlecoin_spend_key = turtlecoin_seed_to_turtlecoin_keys(binascii.unhexlify(u'CFDF58139A7EAA375FA4CB38122D6C548A25E37B783724F47265C662CD6545BD'))
    print('TurtleCoin view  keys: %s'%binascii.hexlify(turtlecoin_view_key))
    print('TurtleCoin spend keys: %s'%binascii.hexlify(turtlecoin_spend_key))
    sys.exit(1);


def max_wlen():
    for l in monero_langs:
        print(' %s %d'%(l['english_language_name'], len(l['words'])))
        wlen = 0
        for w in l['words']:
            if len(w) > wlen:
                wlen = len(w.encode()) 
        print('    wlen = %d'%wlen)
    sys.exit(1)


banner()

if len(sys.argv) != 2 or sys.argv[1] not in ("-h","--help","online","offline"):
    print("Invalid argument")
    usage()    
    sys.exit(1)

lang  = retrieve_language()


if sys.argv[1] == "online":
    get_online_seed(lang)
elif sys.argv[1] == "offline":
    get_offline_seed(lang)
else:
    usage()
