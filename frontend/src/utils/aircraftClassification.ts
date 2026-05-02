// ICAO type code -> aircraft shape classification
export const HELI_TYPES = new Set([
  'R22',
  'R44',
  'R66',
  'B06',
  'B05',
  'B47G',
  'B105',
  'B212',
  'B222',
  'B230',
  'B407',
  'B412',
  'B429',
  'B430',
  'B505',
  'BK17',
  'S55',
  'S58',
  'S61',
  'S64',
  'S70',
  'S76',
  'S92',
  'A109',
  'A119',
  'A139',
  'A169',
  'A189',
  'AW09',
  'EC20',
  'EC25',
  'EC30',
  'EC35',
  'EC45',
  'EC55',
  'EC75',
  'H125',
  'H130',
  'H135',
  'H145',
  'H155',
  'H160',
  'H175',
  'H215',
  'H225',
  'AS32',
  'AS35',
  'AS50',
  'AS55',
  'AS65',
  'MD52',
  'MD60',
  'MDHI',
  'MD90',
  'NOTR',
  'HUEY',
  'GAMA',
  'CABR',
  'EXE',
  'R300',
  'R480',
  'LAMA',
  'ALLI',
  'PUMA',
  'NH90',
  'CH47',
  'UH1',
  'UH60',
  'AH64',
  'MI8',
  'MI24',
  'MI26',
  'MI28',
  'KA52',
  'K32',
  'LYNX',
  'WILD',
  'MRLX',
  'A149',
  'A119',
  // Common heli typecodes seen on the wire that were missing
  'B47G',  // Bell 47
  'H500',  // MD 500 / Hughes 500
  'H269',  // Hughes 269/300
  'EC30',  // EC130 / H130 (also alias)
  'EC35',  // EC135 (also alias)
  'EC45',  // EC145 (also alias)
  'EC75',  // EC175
  'A169',  // AW169
  'A189',  // AW189
  'AW69',  // AW69
  'H60',   // UH-60 / S-70 Black Hawk (military variants on the wire)
  'H47',   // CH-47 Chinook
  'H53',   // CH-53
  'H64',   // AH-64 Apache (alt code seen on the wire)
  'V22',   // V-22 Osprey (rotorcraft for icon purposes)
  'KA32',  // Kamov Ka-32
  'KA50',  // Ka-50
  'MI17',  // Mi-17
  'MI171', // Mi-171
  'MI2',   // Mi-2
  'M530',  // MD 530
  'EXPL',  // MD Explorer
  'GA6C',  // (some heli ICAOs)
  'CABR',  // Cabri G2
  'SK76',  // Sikorsky S-76 alt
]);
export const TURBOPROP_TYPES = new Set([
  'AT43',
  'AT45',
  'AT72',
  'AT73',
  'AT75',
  'AT76',
  'B190',
  'B350',
  'BE20',
  'BE30',
  'BE40',
  'BE9L',
  'BE99',
  'C130',
  'C160',
  'C208',
  'C212',
  'C295',
  'CN35',
  'D228',
  'D328',
  'DHC2',
  'DHC3',
  'DHC4',
  'DHC5',
  'DHC6',
  'DHC7',
  'DHC8',
  'DO28',
  'DH8A',
  'DH8B',
  'DH8C',
  'DH8D',
  'E110',
  'E120',
  'F27',
  'F406',
  'F50',
  'G159',
  'G73T',
  'J328',
  'JS31',
  'JS32',
  'JS41',
  'L188',
  'MA60',
  'M28',
  'N262',
  'P68',
  'P180',
  'PA31',
  'PA42',
  'PC12',
  'PC21',
  'PC24',
  'S2',
  'S340',
  'SF34',
  'SF50',
  'SW4',
  'TRIS',
  'TBM7',
  'TBM8',
  'TBM9',
  'C30J',
  'C5M',
  'AN12',
  'AN24',
  'AN26',
  'AN30',
  'AN32',
  'IL18',
  'L410',
  'Y12',
  'BALL',
  'AEST',
  'AC68',
  'AC80',
  'AC90',
  'AC95',
  'AC11',
  'C172',
  'C182',
  'C206',
  'C210',
  'C310',
  'C337',
  'C402',
  'C414',
  'C421',
  'C425',
  'C441',
  'M20P',
  'M20T',
  'PA28',
  'PA32',
  'PA34',
  'PA44',
  'PA46',
  'PA60',
  'P28A',
  'P28B',
  'P28R',
  'P32R',
  'P46T',
  'SR20',
  'SR22',
  'DA40',
  'DA42',
  'DA62',
  'RV10',
  'BE33',
  'BE35',
  'BE36',
  'BE55',
  'BE58',
  'DR40',
  'TB20',
  'AA5',
  // Common GA / sport / utility / military-utility typecodes seen on the wire
  // that were defaulting to airliner shape
  'AN2',   // Antonov An-2
  'T6',    // T-6 Texan / II
  'TEX2',  // T-6A Texan II
  'PA11',  // PA-11 Cub
  'PA22',  // PA-22 Tri-Pacer
  'PA24',  // PA-24 Comanche
  'PA25',  // PA-25 Pawnee
  'PA38',  // PA-38 Tomahawk
  'PA46',  // PA-46 Malibu / Mirage / Matrix
  'P32R',  // PA-32R Lance/Saratoga
  'P46T',  // PA-46 Meridian (turboprop)
  'C150',  // Cessna 150
  'C152',  // Cessna 152
  'C170',  // Cessna 170
  'C177',  // Cessna 177 Cardinal
  'C180',  // Cessna 180
  'C185',  // Cessna 185
  'C140',  // Cessna 140
  'C120',  // Cessna 120
  'C175',  // Cessna 175
  'C72R',  // Cessna 172 RG
  'C77R',  // Cessna 177 RG
  'C82R',  // Cessna 182 RG
  'C82S',  // Cessna 182 S
  'C82T',  // Cessna 182 T
  'T206',  // Cessna T206 Stationair
  'T210',  // Cessna T210 Centurion
  'C340',  // Cessna 340
  'C56X',  // Citation Excel/XLS  (covered in BIZJET, but harmless)
  'M7',    // Maule M-7
  'M20T',  // Mooney M20 Turbo
  'BE9T',  // King Air F90
  'BE9L',  // King Air 90 (already in main)
  'BE10',  // King Air 100
  'BE30',  // King Air 300 (already in main)
  'BE76',  // Beech Duchess
  'BE95',  // Beech Travel Air
  'BE23',  // Sundowner
  'BE40',  // Beechjet 400 (also in BIZJET, harmless)
  'BE55',  // Baron 55 (already)
  'GA8',   // GippsAero Airvan
  'AC68',  // Aero Commander 680
  'AC80',  // Aero Commander 680
  'AC90',  // Aero Commander 90
  'AC95',  // Aero Commander 95
  'CH7A',  // Champion 7A
  'CH7B',  // Champion 7B
  'CH60',  // Champion 60
  'BL8',   // Bellanca 8 Decathlon
  'TBM7',  // (also already)
  'TBM8',
  'TBM9',
  'M600',  // Piper M600
  'PC21',  // Pilatus PC-21
  'P180',  // Piaggio Avanti
  'CN35',  // CASA CN-235
  'C295',  // CASA C-295
  'C212',  // CASA C-212
  'D228',  // Dornier 228
  'D328',  // Dornier 328
  'L410',  // LET L-410
  'AN24',  // Antonov An-24
  'AN26',  // An-26
  'AN30',  // An-30
  'AN32',  // An-32
  'YK40',  // Yak-40
  'YK42',  // Yak-42 (regional)
  'PARA',  // skydiving
  'GLID',  // glider
  'BALL',  // balloon
  'ULAC',  // ultralight
  'GYRO',  // gyrocopter
  'DRON',  // drone
  'FOX',   // Aviat Husky / sim variants
  'HUSK',  // Husky
  'NAVI',  // Navion
  'AC11',  // Grumman AA-1
  'AA5',   // Grumman AA-5
  'RV4', 'RV6', 'RV7', 'RV8', 'RV9', 'RV10', 'RV12',
  'GLAS',  // Glasair
  'ERCO',  // Ercoupe
  'TAYB',  // Taylorcraft
  'S108',  // Stinson 108
  'S22T',  // SR22T
  'DV20',  // Diamond Katana
  'DA40', 'DA42', 'DA62',
  'SR20', 'SR22',
  'M20P',
  'P28A', 'P28B', 'P28R', 'P28', 'P32R',
  'C172', 'C182', 'C206',
]);
export const BIZJET_TYPES = new Set([
  'ASTR',
  'C25A',
  'C25B',
  'C25C',
  'C25M',
  'C500',
  'C501',
  'C510',
  'C525',
  'C526',
  'C550',
  'C551',
  'C560',
  'C56X',
  'C650',
  'C680',
  'C700',
  'C750',
  'CL30',
  'CL35',
  'CL60',
  'CONI',
  'CRJX',
  'E35L',
  'E45X',
  'E50P',
  'E55P',
  'F2TH',
  'F900',
  'FA10',
  'FA20',
  'FA50',
  'FA7X',
  'FA8X',
  'G100',
  'G150',
  'G200',
  'G280',
  'GA5C',
  'GA6C',
  'GALX',
  'GL5T',
  'GL7T',
  'GLEX',
  'GLF2',
  'GLF3',
  'GLF4',
  'GLF5',
  'GLF6',
  'H25A',
  'H25B',
  'H25C',
  'HA4T',
  'HDJT',
  'LJ23',
  'LJ24',
  'LJ25',
  'LJ28',
  'LJ31',
  'LJ35',
  'LJ40',
  'LJ45',
  'LJ55',
  'LJ60',
  'LJ70',
  'LJ75',
  'MU30',
  'PC24',
  'PRM1',
  'SBR1',
  'SBR2',
  'WW24',
  'BE40',
  'BLCF',
]);

export function classifyAircraft(
  model: string,
  category?: string,
): 'heli' | 'turboprop' | 'bizjet' | 'airliner' {
  const m = (model || '').toUpperCase();
  if (category === 'heli' || HELI_TYPES.has(m)) return 'heli';
  if (BIZJET_TYPES.has(m)) return 'bizjet';
  if (TURBOPROP_TYPES.has(m)) return 'turboprop';
  // Default airliner shape — restores the original behavior where unknown /
  // unrecognized types render as the standard plane silhouette. The earlier
  // attempt to default-down to turboprop made every unidentified flight look
  // smaller and slimmer than it should.
  return 'airliner';
}
