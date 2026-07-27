export type ElementCategory =
  | 'alkali-metal'
  | 'alkaline-earth'
  | 'transition-metal'
  | 'post-transition'
  | 'metalloid'
  | 'nonmetal'
  | 'halogen'
  | 'noble-gas'
  | 'lanthanide'
  | 'actinide'

export interface ElementDatum {
  number: number
  symbol: string
  name: string
  group: number
  period: number
  category: ElementCategory
}

const E = (
  number: number,
  symbol: string,
  name: string,
  group: number,
  period: number,
  category: ElementCategory,
): ElementDatum => ({ number, symbol, name, group, period, category })

export const ELEMENTS: ElementDatum[] = [
  E(1, 'H', 'Hydrogen', 1, 1, 'nonmetal'), E(2, 'He', 'Helium', 18, 1, 'noble-gas'),
  E(3, 'Li', 'Lithium', 1, 2, 'alkali-metal'), E(4, 'Be', 'Beryllium', 2, 2, 'alkaline-earth'),
  E(5, 'B', 'Boron', 13, 2, 'metalloid'), E(6, 'C', 'Carbon', 14, 2, 'nonmetal'),
  E(7, 'N', 'Nitrogen', 15, 2, 'nonmetal'), E(8, 'O', 'Oxygen', 16, 2, 'nonmetal'),
  E(9, 'F', 'Fluorine', 17, 2, 'halogen'), E(10, 'Ne', 'Neon', 18, 2, 'noble-gas'),
  E(11, 'Na', 'Sodium', 1, 3, 'alkali-metal'), E(12, 'Mg', 'Magnesium', 2, 3, 'alkaline-earth'),
  E(13, 'Al', 'Aluminium', 13, 3, 'post-transition'), E(14, 'Si', 'Silicon', 14, 3, 'metalloid'),
  E(15, 'P', 'Phosphorus', 15, 3, 'nonmetal'), E(16, 'S', 'Sulfur', 16, 3, 'nonmetal'),
  E(17, 'Cl', 'Chlorine', 17, 3, 'halogen'), E(18, 'Ar', 'Argon', 18, 3, 'noble-gas'),
  E(19, 'K', 'Potassium', 1, 4, 'alkali-metal'), E(20, 'Ca', 'Calcium', 2, 4, 'alkaline-earth'),
  E(21, 'Sc', 'Scandium', 3, 4, 'transition-metal'), E(22, 'Ti', 'Titanium', 4, 4, 'transition-metal'),
  E(23, 'V', 'Vanadium', 5, 4, 'transition-metal'), E(24, 'Cr', 'Chromium', 6, 4, 'transition-metal'),
  E(25, 'Mn', 'Manganese', 7, 4, 'transition-metal'), E(26, 'Fe', 'Iron', 8, 4, 'transition-metal'),
  E(27, 'Co', 'Cobalt', 9, 4, 'transition-metal'), E(28, 'Ni', 'Nickel', 10, 4, 'transition-metal'),
  E(29, 'Cu', 'Copper', 11, 4, 'transition-metal'), E(30, 'Zn', 'Zinc', 12, 4, 'transition-metal'),
  E(31, 'Ga', 'Gallium', 13, 4, 'post-transition'), E(32, 'Ge', 'Germanium', 14, 4, 'metalloid'),
  E(33, 'As', 'Arsenic', 15, 4, 'metalloid'), E(34, 'Se', 'Selenium', 16, 4, 'nonmetal'),
  E(35, 'Br', 'Bromine', 17, 4, 'halogen'), E(36, 'Kr', 'Krypton', 18, 4, 'noble-gas'),
  E(37, 'Rb', 'Rubidium', 1, 5, 'alkali-metal'), E(38, 'Sr', 'Strontium', 2, 5, 'alkaline-earth'),
  E(39, 'Y', 'Yttrium', 3, 5, 'transition-metal'), E(40, 'Zr', 'Zirconium', 4, 5, 'transition-metal'),
  E(41, 'Nb', 'Niobium', 5, 5, 'transition-metal'), E(42, 'Mo', 'Molybdenum', 6, 5, 'transition-metal'),
  E(43, 'Tc', 'Technetium', 7, 5, 'transition-metal'), E(44, 'Ru', 'Ruthenium', 8, 5, 'transition-metal'),
  E(45, 'Rh', 'Rhodium', 9, 5, 'transition-metal'), E(46, 'Pd', 'Palladium', 10, 5, 'transition-metal'),
  E(47, 'Ag', 'Silver', 11, 5, 'transition-metal'), E(48, 'Cd', 'Cadmium', 12, 5, 'transition-metal'),
  E(49, 'In', 'Indium', 13, 5, 'post-transition'), E(50, 'Sn', 'Tin', 14, 5, 'post-transition'),
  E(51, 'Sb', 'Antimony', 15, 5, 'metalloid'), E(52, 'Te', 'Tellurium', 16, 5, 'metalloid'),
  E(53, 'I', 'Iodine', 17, 5, 'halogen'), E(54, 'Xe', 'Xenon', 18, 5, 'noble-gas'),
  E(55, 'Cs', 'Caesium', 1, 6, 'alkali-metal'), E(56, 'Ba', 'Barium', 2, 6, 'alkaline-earth'),
  E(57, 'La', 'Lanthanum', 3, 6, 'lanthanide'), E(72, 'Hf', 'Hafnium', 4, 6, 'transition-metal'),
  E(73, 'Ta', 'Tantalum', 5, 6, 'transition-metal'), E(74, 'W', 'Tungsten', 6, 6, 'transition-metal'),
  E(75, 'Re', 'Rhenium', 7, 6, 'transition-metal'), E(76, 'Os', 'Osmium', 8, 6, 'transition-metal'),
  E(77, 'Ir', 'Iridium', 9, 6, 'transition-metal'), E(78, 'Pt', 'Platinum', 10, 6, 'transition-metal'),
  E(79, 'Au', 'Gold', 11, 6, 'transition-metal'), E(80, 'Hg', 'Mercury', 12, 6, 'transition-metal'),
  E(81, 'Tl', 'Thallium', 13, 6, 'post-transition'), E(82, 'Pb', 'Lead', 14, 6, 'post-transition'),
  E(83, 'Bi', 'Bismuth', 15, 6, 'post-transition'), E(84, 'Po', 'Polonium', 16, 6, 'post-transition'),
  E(85, 'At', 'Astatine', 17, 6, 'halogen'), E(86, 'Rn', 'Radon', 18, 6, 'noble-gas'),
  E(87, 'Fr', 'Francium', 1, 7, 'alkali-metal'), E(88, 'Ra', 'Radium', 2, 7, 'alkaline-earth'),
  E(89, 'Ac', 'Actinium', 3, 7, 'actinide'), E(104, 'Rf', 'Rutherfordium', 4, 7, 'transition-metal'),
  E(105, 'Db', 'Dubnium', 5, 7, 'transition-metal'), E(106, 'Sg', 'Seaborgium', 6, 7, 'transition-metal'),
  E(107, 'Bh', 'Bohrium', 7, 7, 'transition-metal'), E(108, 'Hs', 'Hassium', 8, 7, 'transition-metal'),
  E(109, 'Mt', 'Meitnerium', 9, 7, 'transition-metal'), E(110, 'Ds', 'Darmstadtium', 10, 7, 'transition-metal'),
  E(111, 'Rg', 'Roentgenium', 11, 7, 'transition-metal'), E(112, 'Cn', 'Copernicium', 12, 7, 'transition-metal'),
  E(113, 'Nh', 'Nihonium', 13, 7, 'post-transition'), E(114, 'Fl', 'Flerovium', 14, 7, 'post-transition'),
  E(115, 'Mc', 'Moscovium', 15, 7, 'post-transition'), E(116, 'Lv', 'Livermorium', 16, 7, 'post-transition'),
  E(117, 'Ts', 'Tennessine', 17, 7, 'halogen'), E(118, 'Og', 'Oganesson', 18, 7, 'noble-gas'),
  E(58, 'Ce', 'Cerium', 4, 9, 'lanthanide'), E(59, 'Pr', 'Praseodymium', 5, 9, 'lanthanide'),
  E(60, 'Nd', 'Neodymium', 6, 9, 'lanthanide'), E(61, 'Pm', 'Promethium', 7, 9, 'lanthanide'),
  E(62, 'Sm', 'Samarium', 8, 9, 'lanthanide'), E(63, 'Eu', 'Europium', 9, 9, 'lanthanide'),
  E(64, 'Gd', 'Gadolinium', 10, 9, 'lanthanide'), E(65, 'Tb', 'Terbium', 11, 9, 'lanthanide'),
  E(66, 'Dy', 'Dysprosium', 12, 9, 'lanthanide'), E(67, 'Ho', 'Holmium', 13, 9, 'lanthanide'),
  E(68, 'Er', 'Erbium', 14, 9, 'lanthanide'), E(69, 'Tm', 'Thulium', 15, 9, 'lanthanide'),
  E(70, 'Yb', 'Ytterbium', 16, 9, 'lanthanide'), E(71, 'Lu', 'Lutetium', 17, 9, 'lanthanide'),
  E(90, 'Th', 'Thorium', 4, 10, 'actinide'), E(91, 'Pa', 'Protactinium', 5, 10, 'actinide'),
  E(92, 'U', 'Uranium', 6, 10, 'actinide'), E(93, 'Np', 'Neptunium', 7, 10, 'actinide'),
  E(94, 'Pu', 'Plutonium', 8, 10, 'actinide'), E(95, 'Am', 'Americium', 9, 10, 'actinide'),
  E(96, 'Cm', 'Curium', 10, 10, 'actinide'), E(97, 'Bk', 'Berkelium', 11, 10, 'actinide'),
  E(98, 'Cf', 'Californium', 12, 10, 'actinide'), E(99, 'Es', 'Einsteinium', 13, 10, 'actinide'),
  E(100, 'Fm', 'Fermium', 14, 10, 'actinide'), E(101, 'Md', 'Mendelevium', 15, 10, 'actinide'),
  E(102, 'No', 'Nobelium', 16, 10, 'actinide'), E(103, 'Lr', 'Lawrencium', 17, 10, 'actinide'),
]
