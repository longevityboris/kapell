"""Paths and constants shared by the organ scripts."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = Path('/Users/biobook/Music/SampleLibraries')
ORGAN_LIB = LIB / 'Organ'
SET_DIR = ORGAN_LIB / 'NorrfjardenChurch'
ODF = SET_DIR / 'NorrfjardenChurch.organ'
SET_URL = 'http://www.familjenpalo.se/sites/default/files/sampleset/packages/NorrfjardenChurch.orgue'
SET_BYTES = 2045915742
SET_SHA256 = 'f330a8f9f67ffa6b04d72098fc340db817f680421a51cea4e35a77618f3085eb'

# Church impulse response: OpenAIR, Lady Chapel, St Albans Cathedral, ORTF stereo, position A
# (CC BY 4.0), through audEERING's public mirror of the OpenAIR library.
IR_DIR = LIB / 'IR' / 'OpenAIR'
IR_FILE = IR_DIR / 'lady_chapel_st_albans_cathedral__stereo__stalbans_a_ortf.wav'
IR_URL = ('https://s3.dualstack.eu-north-1.amazonaws.com/audb-public/openair/media/1.0.0/'
          '8b50a145-8ea6-8b65-e56b-4f6e832b0011.zip')
IR_MD5 = '1e57722d6edfe8f121ab3f110adb3d45'

PIPES_JSON = HERE / 'data' / 'norrfjarden_pipes.json'   # measured pipe model (analyze_organ.py)
REGISTRATIONS_JSON = HERE / 'registrations.json'

WVUNPACK = '/opt/homebrew/bin/wvunpack'
SR = 48000
