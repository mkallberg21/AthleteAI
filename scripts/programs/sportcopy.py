"""Per-sport editorial copy for the director summaries.

Kept apart from the template so the writing can be read as writing. Every
sport gets a real sentence about what its athletes actually do between
sessions, rather than the sport's name dropped into a form letter.
"""

# (thesis, the between-sessions reality, the one thing this sport's directors
#  worry about that the product speaks to, and what an athlete of this sport
#  actually does alone -- the last one written out rather than taken from the
#  catalog, which would have produced "a child who does face-off clamp".)
SPORT = {
 "lacrosse": (
   "Wall ball is the whole sport, and nobody has ever been able to count it.",
   "A player against a wall for twenty minutes is the single highest-value "
   "thing they can do alone. It is also completely invisible to you: the "
   "player says “I did wall ball” and that is the whole record.",
   "offhand development, which every coach preaches and nobody can verify",
   'wall ball in the driveway'),
 "basketball": (
   "Shots in a driveway are only worth something if somebody knows they happened.",
   "Form shooting, ball handling and defensive slides are all solo work, and "
   "all of it currently reaches you as a self-report at the next practice.",
   "the gap between the players who work alone and the players who say they do",
   'form shooting in the driveway'),
 "soccer": (
   "Touches are the currency, and they are counted for the first time here.",
   "Juggling, wall passing and first-touch work are what separate players at "
   "this age, and they happen in gardens and car parks you never see.",
   "heading, which this product refuses to count at all. See page four",
   'juggling in the garden'),
 "volleyball": (
   "Serving and setting reps against a wall, finally on the record.",
   "The repetitions that build a setter's hands happen alone against a garage "
   "door, in volumes nobody has ever measured.",
   "shoulder volume in a sport that swings overhead all season",
   'setting against the garage door'),
 "baseball": (
   "The throwing arm is the asset, and this is the only app that counts it down.",
   "Long toss, fielding and swing work happen in back gardens all winter, "
   "entirely outside any pitch count your league keeps.",
   "arm injuries, and the throws that never appear in a pitch count",
   'swing work in the garden'),
 "softball": (
   "The throwing arm is the asset, and this is the only app that counts it down.",
   "Fielding reps and swing work happen in back gardens all winter, entirely "
   "outside any count your league keeps.",
   "arm injuries, and the throws that never appear in a pitch count",
   'swing work in the garden'),
 "tennis": (
   "Serve and groundstroke volume, measured off a wall.",
   "A wall is the cheapest hitting partner in the sport, and the reps hit "
   "against one have never appeared in any record of a player's week.",
   "shoulder and elbow load in a one-sided sport",
   'hitting against a wall'),
 "hockey": (
   "Stickhandling and shooting off the ice, where most of the work is.",
   "Ice time is expensive and rationed. The players who improve are the ones "
   "doing puck work on a driveway board, and that is unrecorded.",
   "making off-ice work visible when ice time is the budget line",
   'stickhandling on a driveway board'),
 "football": (
   "The throwing arm, and the explosive work that separates the roster.",
   "Quarterbacks throw all summer with no count anywhere, and everyone else "
   "is doing conditioning you have to take their word for.",
   "quarterback arm volume, which no governing body counts at all",
   'throwing in the back garden'),
 "rugby": (
   "Handling and conditioning, honestly counted, and contact left alone.",
   "Passing and fitness work is solo and unrecorded. Contact work is not in "
   "this product at all, and that is a deliberate decision, not a gap.",
   "conditioning honesty without pushing unsupervised contact",
   'handling work in the garden'),
 "gymnastics": (
   "Conditioning only. This product will not score how a body looks.",
   "Between sessions the useful work is strength and shape holds. This app "
   "counts that work and refuses to grade artistry, line or appearance.",
   "a sport with a documented eating-disorder problem, and an app that scores "
   "effort rather than aesthetics",
   'conditioning at home'),
 "cheer": (
   "Conditioning only. This product will not score how a body looks.",
   "Between sessions the useful work is strength, holds and tumbling "
   "conditioning, not appearance, and not stunting without spotters.",
   "conditioning athletes safely without unsupervised stunting",
   'conditioning at home'),
 "dance": (
   "Conditioning only. This product will not score how a body looks.",
   "The strength and endurance work behind the performance is what this "
   "counts. Artistry is not scored, and never will be.",
   "load and overuse in a sport that trains most days of the week",
   'strength work at home'),
 "track": (
   "Strength and plyometric work between sessions, plus an honest run log.",
   "The running itself is self-reported and earns nothing. The strength and "
   "jump work around it is what the camera can actually verify.",
   "training load, and the week a distance runner quietly doubles their mileage",
   'strength and jump work'),
 "cross_country": (
   "Strength and plyometric work between sessions, plus an honest run log.",
   "The running itself is self-reported and earns nothing. The strength work "
   "around it is what the camera can verify, and it is what prevents injuries.",
   "mileage jumps, which the load monitor flags before they become injuries",
   'strength work after a run'),
 "swimming": (
   "Dryland only. Nothing in this product asks an athlete into the water alone.",
   "Pool time is coached and supervised. What is not is the dryland work, and "
   "that is the only thing here that earns anything.",
   "shoulder volume, and never encouraging an unsupervised swim",
   'dryland work'),
}
