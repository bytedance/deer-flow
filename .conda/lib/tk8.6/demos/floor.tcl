# floor.tcl --
#
# This demonstration script creates a canvas widet that displays the
# floorplan for DEC's Western Research Laboratory.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# floorDisplay --
# Recreate the floorplan display in the canvas given by "w".  The
# floor given by "active" is displayed on top with its office structure
# visible.
#
# Arguments:
# w -		Name of the canvas window.
# active -	Number of active floor (1, 2, or 3).

proc floorDisplay {w active} {
    global floorLabels floorItems colors activeFloor

    if {$activeFloor == $active} {
	return
    }

    $w delete all
    set activeFloor $active

    # First go through the three floors, displaying the backgrounds for
    # each floor.

    bg1 $w $colors(bg1) $colors(outline1)
    bg2 $w $colors(bg2) $colors(outline2)
    bg3 $w $colors(bg3) $colors(outline3)

    # Raise the background for the active floor so that it's on top.

    $w raise floor$active

    # Create a dummy item just to mark this point in the display list,
    # so we can insert highlights here.

    $w create rect 0 100 1 101 -fill {} -outline {} -tags marker

    # Add the walls and labels for the active floor, along with
    # transparent polygons that define the rooms on the floor.
    # Make sure that the room polygons are on top.

    catch {unset floorLabels}
    catch {unset floorItems}
    fg$active $w $colors(offices)
    $w raise room

    # Offset the floors diagonally from each other.

    $w move floor1 2c 2c
    $w move floor2 1c 1c

    # Create items for the room entry and its label.

    $w create window 600 100 -anchor w -window $w.entry
    $w create text 600 100 -anchor e -text "Room: "

    $w config -scrollregion [$w bbox all]
}

# newRoom --
# This procedure is invoked whenever the mouse enters a room
# in the floorplan.  It changes tags so that the current room is
# highlighted.
#
# Arguments:
# w  -		The name of the canvas window.

proc newRoom w {
    global currentRoom floorLabels

    set id [$w find withtag current]
    if {$id != ""} {
	set currentRoom $floorLabels($id)
    }
    update idletasks
}

# roomChanged --
# This procedure is invoked whenever the currentRoom variable changes.
# It highlights the current room and unhighlights any previous room.
#
# Arguments:
# w -		The canvas window displaying the floorplan.
# args -	Not used.

proc roomChanged {w args} {
    global currentRoom floorItems colors
    $w delete highlight
    if {[catch {set item $floorItems($currentRoom)}]} {
	return
    }
    set new [eval \
	"$w create polygon [$w coords $item] -fill $colors(active) \
	-outline {} -tags highlight"]
    $w raise $new marker
}

# bg1 --
# This procedure represents part of the floorplan database.  When
# invoked, it instantiates the background information for the first
# floor.
#
# Arguments:
# w -		The canvas window.
# fill -	Fill color to use for the floor's background.
# outline -	Color to use for the floor's outline.

proc bg1 {w fill outline} {
    $w create polygon 347 80 349 82 351 84 353 85 363 92 375 99 386 104 \
	386 129 398 129 398 162 484 162 484 129 559 129 559 133 725 \
	133 725 129 802 129 802 389 644 389 644 391 559 391 559 327 \
	508 327 508 311 484 311 484 278 395 278 395 288 400 288 404 \
	288 409 290 413 292 418 297 421 302 422 309 421 318 417 325 \
	411 330 405 332 397 333 344 333 340 334 336 336 335 338 332 \
	342 331 347 332 351 334 354 336 357 341 359 340 360 335 363 \
	331 365 326 366 304 366 304 355 258 355 258 387 60 387 60 391 \
	0 391 0 337 3 337 3 114 8 114 8 25 30 25 30 5 93 5 98 5 104 7 \
	110 10 116 16 119 20 122 28 123 32 123 68 220 68 220 34 221 \
	22 223 17 227 13 231 8 236 4 242 2 246 0 260 0 283 1 300 5 \
	321 14 335 22 348 25 365 29 363 39 358 48 352 56 337 70 \
	344 76 347 80 \
	-tags {floor1 bg} -fill $fill -outline {}
    $w create line 386 129 398 129 -fill $outline -tags {floor1 bg}
    $w create line 258 355 258 387 -fill $outline -tags {floor1 bg}
    $w create line 60 387 60 391 -fill $outline -tags {floor1 bg}
    $w create line 0 337 0 391 -fill $outline -tags {floor1 bg}
    $w create line 60 391 0 391 -fill $outline -tags {floor1 bg}
    $w create line 3 114 3 337 -fill $outline -tags {floor1 bg}
    $w create line 258 387 60 387 -fill $outline -tags {floor1 bg}
    $w create line 484 162 398 162 -fill $outline -tags {floor1 bg}
    $w create line 398 162 398 129 -fill $outline -tags {floor1 bg}
    $w create line 484 278 484 311 -fill $outline -tags {floor1 bg}
    $w create line 484 311 508 311 -fill $outline -tags {floor1 bg}
    $w create line 508 327 508 311 -fill $outline -tags {floor1 bg}
    $w create line 559 327 508 327 -fill $outline -tags {floor1 bg}
    $w create line 644 391 559 391 -fill $outline -tags {floor1 bg}
    $w create line 644 389 644 391 -fill $outline -tags {floor1 bg}
    $w create line 559 129 484 129 -fill $outline -tags {floor1 bg}
    $w create line 484 162 484 129 -fill $outline -tags {floor1 bg}
    $w create line 725 133 559 133 -fill $outline -tags {floor1 bg}
    $w create line 559 129 559 133 -fill $outline -tags {floor1 bg}
    $w create line 725 129 802 129 -fill $outline -tags {floor1 bg}
    $w create line 802 389 802 129 -fill $outline -tags {floor1 bg}
    $w create line 3 337 0 337 -fill $outline -tags {floor1 bg}
    $w create line 559 391 559 327 -fill $outline -tags {floor1 bg}
    $w create line 802 389 644 389 -fill $outline -tags {floor1 bg}
    $w create line 725 133 725 129 -fill $outline -tags {floor1 bg}
    $w create line 8 25 8 114 -fill $outline -tags {floor1 bg}
    $w create line 8 114 3 114 -fill $outline -tags {floor1 bg}
    $w create line 30 25 8 25 -fill $outline -tags {floor1 bg}
    $w create line 484 278 395 278 -fill $outline -tags {floor1 bg}
    $w create line 30 25 30 5 -fill $outline -tags {floor1 bg}
    $w create line 93 5 30 5 -fill $outline -tags {floor1 bg}
    $w create line 98 5 93 5 -fill $outline -tags {floor1 bg}
    $w create line 104 7 98 5 -fill $outline -tags {floor1 bg}
    $w create line 110 10 104 7 -fill $outline -tags {floor1 bg}
    $w create line 116 16 110 10 -fill $outline -tags {floor1 bg}
    $w create line 119 20 116 16 -fill $outline -tags {floor1 bg}
    $w create line 122 28 119 20 -fill $outline -tags {floor1 bg}
    $w create line 123 32 122 28 -fill $outline -tags {floor1 bg}
    $w create line 123 68 123 32 -fill $outline -tags {floor1 bg}
    $w create line 220 68 123 68 -fill $outline -tags {floor1 bg}
    $w create line 386 129 386 104 -fill $outline -tags {floor1 bg}
    $w create line 386 104 375 99 -fill $outline -tags {floor1 bg}
    $w create line 375 99 363 92 -fill $outline -tags {floor1 bg}
    $w create line 353 85 363 92 -fill $outline -tags {floor1 bg}
    $w create line 220 68 220 34 -fill $outline -tags {floor1 bg}
    $w create line 337 70 352 56 -fill $outline -tags {floor1 bg}
    $w create line 352 56 358 48 -fill $outline -tags {floor1 bg}
    $w create line 358 48 363 39 -fill $outline -tags {floor1 bg}
    $w create line 363 39 365 29 -fill $outline -tags {floor1 bg}
    $w create line 365 29 348 25 -fill $outline -tags {floor1 bg}
    $w create line 348 25 335 22 -fill $outline -tags {floor1 bg}
    $w create line 335 22 321 14 -fill $outline -tags {floor1 bg}
    $w create line 321 14 300 5 -fill $outline -tags {floor1 bg}
    $w create line 300 5 283 1 -fill $outline -tags {floor1 bg}
    $w create line 283 1 260 0 -fill $outline -tags {floor1 bg}
    $w create line 260 0 246 0 -fill $outline -tags {floor1 bg}
    $w create line 246 0 242 2 -fill $outline -tags {floor1 bg}
    $w create line 242 2 236 4 -fill $outline -tags {floor1 bg}
    $w create line 236 4 231 8 -fill $outline -tags {floor1 bg}
    $w create line 231 8 227 13 -fill $outline -tags {floor1 bg}
    $w create line 223 17 227 13 -fill $outline -tags {floor1 bg}
    $w create line 221 22 223 17 -fill $outline -tags {floor1 bg}
    $w create line 220 34 221 22 -fill $outline -tags {floor1 bg}
    $w create line 340 360 335 363 -fill $outline -tags {floor1 bg}
    $w create line 335 363 331 365 -fill $outline -tags {floor1 bg}
    $w create line 331 365 326 366 -fill $outline -tags {floor1 bg}
    $w create line 326 366 304 366 -fill $outline -tags {floor1 bg}
    $w create line 304 355 304 366 -fill $outline -tags {floor1 bg}
    $w create line 395 288 400 288 -fill $outline -tags {floor1 bg}
    $w create line 404 288 400 288 -fill $outline -tags {floor1 bg}
    $w create line 409 290 404 288 -fill $outline -tags {floor1 bg}
    $w create line 413 292 409 290 -fill $outline -tags {floor1 bg}
    $w create line 418 297 413 292 -fill $outline -tags {floor1 bg}
    $w create line 421 302 418 297 -fill $outline -tags {floor1 bg}
    $w create line 422 309 421 302 -fill $outline -tags {floor1 bg}
    $w create line 421 318 422 309 -fill $outline -tags {floor1 bg}
    $w create line 421 318 417 325 -fill $outline -tags {floor1 bg}
    $w create line 417 325 411 330 -fill $outline -tags {floor1 bg}
    $w create line 411 330 405 332 -fill $outline -tags {floor1 bg}
    $w create line 405 332 397 333 -fill $outline -tags {floor1 bg}
    $w create line 397 333 344 333 -fill $outline -tags {floor1 bg}
    $w create line 344 333 340 334 -fill $outline -tags {floor1 bg}
    $w create line 340 334 336 336 -fill $outline -tags {floor1 bg}
    $w create line 336 336 335 338 -fill $outline -tags {floor1 bg}
    $w create line 335 338 332 342 -fill $outline -tags {floor1 bg}
    $w create line 331 347 332 342 -fill $outline -tags {floor1 bg}
    $w create line 332 351 331 347 -fill $outline -tags {floor1 bg}
    $w create line 334 354 332 351 -fill $outline -tags {floor1 bg}
    $w create line 336 357 334 354 -fill $outline -tags {floor1 bg}
    $w create line 341 359 336 357 -fill $outline -tags {floor1 bg}
    $w create line 341 359 340 360 -fill $outline -tags {floor1 bg}
    $w create line 395 288 395 278 -fill $outline -tags {floor1 bg}
    $w create line 304 355 258 355 -fill $outline -tags {floor1 bg}
    $w create line 347 80 344 76 -fill $outline -tags {floor1 bg}
    $w create line 344 76 337 70 -fill $outline -tags {floor1 bg}
    $w create line 349 82 347 80 -fill $outline -tags {floor1 bg}
    $w create line 351 84 349 82 -fill $outline -tags {floor1 bg}
    $w create line 353 85 351 84 -fill $outline -tags {floor1 bg}
}

# bg2 --
# This procedure represents part of the floorplan database.  When
# invoked, it instantiates the background information for the second
# floor.
#
# Arguments:
# w -		The canvas window.
# fill -	Fill color to use for the floor's background.
# outline -	Color to use for the floor's outline.

proc bg2 {w fill outline} {
    $w create polygon 559 129 484 129 484 162 398 162 398 129 315 129 \
	315 133 176 133 176 129 96 129 96 133 3 133 3 339 0 339 0 391 \
	60 391 60 387 258 387 258 329 350 329 350 311 395 311 395 280 \
	484 280 484 311 508 311 508 327 558 327 558 391 644 391 644 \
	367 802 367 802 129 725 129 725 133 559 133 559 129 \
	-tags {floor2 bg} -fill $fill -outline {}
    $w create line 350 311 350 329 -fill $outline -tags {floor2 bg}
    $w create line 398 129 398 162 -fill $outline -tags {floor2 bg}
    $w create line 802 367 802 129 -fill $outline -tags {floor2 bg}
    $w create line 802 129 725 129 -fill $outline -tags {floor2 bg}
    $w create line 725 133 725 129 -fill $outline -tags {floor2 bg}
    $w create line 559 129 559 133 -fill $outline -tags {floor2 bg}
    $w create line 559 133 725 133 -fill $outline -tags {floor2 bg}
    $w create line 484 162 484 129 -fill $outline -tags {floor2 bg}
    $w create line 559 129 484 129 -fill $outline -tags {floor2 bg}
    $w create line 802 367 644 367 -fill $outline -tags {floor2 bg}
    $w create line 644 367 644 391 -fill $outline -tags {floor2 bg}
    $w create line 644 391 558 391 -fill $outline -tags {floor2 bg}
    $w create line 558 327 558 391 -fill $outline -tags {floor2 bg}
    $w create line 558 327 508 327 -fill $outline -tags {floor2 bg}
    $w create line 508 327 508 311 -fill $outline -tags {floor2 bg}
    $w create line 484 311 508 311 -fill $outline -tags {floor2 bg}
    $w create line 484 280 484 311 -fill $outline -tags {floor2 bg}
    $w create line 398 162 484 162 -fill $outline -tags {floor2 bg}
    $w create line 484 280 395 280 -fill $outline -tags {floor2 bg}
    $w create line 395 280 395 311 -fill $outline -tags {floor2 bg}
    $w create line 258 387 60 387 -fill $outline -tags {floor2 bg}
    $w create line 3 133 3 339 -fill $outline -tags {floor2 bg}
    $w create line 3 339 0 339 -fill $outline -tags {floor2 bg}
    $w create line 60 391 0 391 -fill $outline -tags {floor2 bg}
    $w create line 0 339 0 391 -fill $outline -tags {floor2 bg}
    $w create line 60 387 60 391 -fill $outline -tags {floor2 bg}
    $w create line 258 329 258 387 -fill $outline -tags {floor2 bg}
    $w create line 350 329 258 329 -fill $outline -tags {floor2 bg}
    $w create line 395 311 350 311 -fill $outline -tags {floor2 bg}
    $w create line 398 129 315 129 -fill $outline -tags {floor2 bg}
    $w create line 176 133 315 133 -fill $outline -tags {floor2 bg}
    $w create line 176 129 96 129 -fill $outline -tags {floor2 bg}
    $w create line 3 133 96 133 -fill $outline -tags {floor2 bg}
    $w create line 315 133 315 129 -fill $outline -tags {floor2 bg}
    $w create line 176 133 176 129 -fill $outline -tags {floor2 bg}
    $w create line 96 133 96 129 -fill $outline -tags {floor2 bg}
}

# bg3 --
# This procedure represents part of the floorplan database.  When
# invoked, it instantiates the background information for the third
# floor.
#
# Arguments:
# w -		The canvas window.
# fill -	Fill color to use for the floor's background.
# outline -	Color to use for the floor's outline.

proc bg3 {w fill outline} {
    $w create polygon 159 300 107 300 107 248 159 248 159 129 96 129 96 \
	133 21 133 21 331 0 331 0 391 60 391 60 370 159 370 159 300 \
	-tags {floor3 bg} -fill $fill -outline {}
    $w create polygon 258 370 258 329 350 329 350 311 399 311 399 129 \
	315 129 315 133 176 133 176 129 159 129 159 370 258 370 \
	-tags {floor3 bg} -fill $fill -outline {}
    $w create line 96 133 96 129 -fill $outline -tags {floor3 bg}
    $w create line 176 129 96 129 -fill $outline -tags {floor3 bg}
    $w create line 176 129 176 133 -fill $outline -tags {floor3 bg}
    $w create line 315 133 176 133 -fill $outline -tags {floor3 bg}
    $w create line 315 133 315 129 -fill $outline -tags {floor3 bg}
    $w create line 399 129 315 129 -fill $outline -tags {floor3 bg}
    $w create line 399 311 399 129 -fill $outline -tags {floor3 bg}
    $w create line 399 311 350 311 -fill $outline -tags {floor3 bg}
    $w create line 350 329 350 311 -fill $outline -tags {floor3 bg}
    $w create line 350 329 258 329 -fill $outline -tags {floor3 bg}
    $w create line 258 370 258 329 -fill $outline -tags {floor3 bg}
    $w create line 60 370 258 370 -fill $outline -tags {floor3 bg}
    $w create line 60 370 60 391 -fill $outline -tags {floor3 bg}
    $w create line 60 391 0 391 -fill $outline -tags {floor3 bg}
    $w create line 0 391 0 331 -fill $outline -tags {floor3 bg}
    $w create line 21 331 0 331 -fill $outline -tags {floor3 bg}
    $w create line 21 331 21 133 -fill $outline -tags {floor3 bg}
    $w create line 96 133 21 133 -fill $outline -tags {floor3 bg}
    $w create line 107 300 159 300 159 248 107 248 107 300 \
	    -fill $outline -tags {floor3 bg}
}

# fg1 --
# This procedure represents part of the floorplan database.  When
# invoked, it instantiates the foreground information for the first
# floor (office outlines and numbers).
#
# Arguments:
# w -		The canvas window.
# color -	Color to use for drawing foreground information.

proc fg1 {w color} {
    global floorLabels floorItems
    set i [$w create polygon 375 246 375 172 341 172 341 246 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 101
    set {floorItems(101)} $i
    $w create text 358 209 -text 101 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 307 240 339 240 339 206 307 206 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) {Pub Lift1}
    set {floorItems(Pub Lift1)} $i
    $w create text 323 223 -text {Pub Lift1} -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 339 205 307 205 307 171 339 171 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) {Priv Lift1}
    set {floorItems(Priv Lift1)} $i
    $w create text 323 188 -text {Priv Lift1} -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 42 389 42 337 1 337 1 389 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 110
    set {floorItems(110)} $i
    $w create text 21.5 363 -text 110 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 59 389 59 385 90 385 90 337 44 337 44 389 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 109
    set {floorItems(109)} $i
    $w create text 67 363 -text 109 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 51 300 51 253 6 253 6 300 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 111
    set {floorItems(111)} $i
    $w create text 28.5 276.5 -text 111 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 98 248 98 309 79 309 79 248 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 117B
    set {floorItems(117B)} $i
    $w create text 88.5 278.5 -text 117B -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 51 251 51 204 6 204 6 251 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 112
    set {floorItems(112)} $i
    $w create text 28.5 227.5 -text 112 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 6 156 51 156 51 203 6 203 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 113
    set {floorItems(113)} $i
    $w create text 28.5 179.5 -text 113 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 85 169 79 169 79 192 85 192 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 117A
    set {floorItems(117A)} $i
    $w create text 82 180.5 -text 117A -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 77 302 77 168 53 168 53 302 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 117
    set {floorItems(117)} $i
    $w create text 65 235 -text 117 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 51 155 51 115 6 115 6 155 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 114
    set {floorItems(114)} $i
    $w create text 28.5 135 -text 114 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 95 115 53 115 53 168 95 168 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 115
    set {floorItems(115)} $i
    $w create text 74 141.5 -text 115 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 87 113 87 27 10 27 10 113 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 116
    set {floorItems(116)} $i
    $w create text 48.5 70 -text 116 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 89 91 128 91 128 113 89 113 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 118
    set {floorItems(118)} $i
    $w create text 108.5 102 -text 118 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 178 128 178 132 216 132 216 91 163 91 163 112 149 112 149 128 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 120
    set {floorItems(120)} $i
    $w create text 189.5 111.5 -text 120 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 79 193 87 193 87 169 136 169 136 192 156 192 156 169 175 169 175 246 79 246 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 122
    set {floorItems(122)} $i
    $w create text 131 207.5 -text 122 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 138 169 154 169 154 191 138 191 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 121
    set {floorItems(121)} $i
    $w create text 146 180 -text 121 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 99 300 126 300 126 309 99 309 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 106A
    set {floorItems(106A)} $i
    $w create text 112.5 304.5 -text 106A -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 128 299 128 309 150 309 150 248 99 248 99 299 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 105
    set {floorItems(105)} $i
    $w create text 124.5 278.5 -text 105 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 174 309 174 300 152 300 152 309 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 106B
    set {floorItems(106B)} $i
    $w create text 163 304.5 -text 106B -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 176 299 176 309 216 309 216 248 152 248 152 299 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 104
    set {floorItems(104)} $i
    $w create text 184 278.5 -text 104 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 138 385 138 337 91 337 91 385 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 108
    set {floorItems(108)} $i
    $w create text 114.5 361 -text 108 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 256 337 140 337 140 385 256 385 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 107
    set {floorItems(107)} $i
    $w create text 198 361 -text 107 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 300 353 300 329 260 329 260 353 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) Smoking
    set {floorItems(Smoking)} $i
    $w create text 280 341 -text Smoking -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 314 135 314 170 306 170 306 246 177 246 177 135 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 123
    set {floorItems(123)} $i
    $w create text 245.5 190.5 -text 123 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 217 248 301 248 301 326 257 326 257 310 217 310 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 103
    set {floorItems(103)} $i
    $w create text 259 287 -text 103 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 396 188 377 188 377 169 316 169 316 131 396 131 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 124
    set {floorItems(124)} $i
    $w create text 356 150 -text 124 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 397 226 407 226 407 189 377 189 377 246 397 246 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 125
    set {floorItems(125)} $i
    $w create text 392 217.5 -text 125 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 399 187 409 187 409 207 474 207 474 164 399 164 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 126
    set {floorItems(126)} $i
    $w create text 436.5 185.5 -text 126 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 409 209 409 229 399 229 399 253 486 253 486 239 474 239 474 209 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 127
    set {floorItems(127)} $i
    $w create text 436.5 231 -text 127 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 501 164 501 174 495 174 495 188 490 188 490 204 476 204 476 164 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) MShower
    set {floorItems(MShower)} $i
    $w create text 488.5 184 -text MShower -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 497 176 513 176 513 204 492 204 492 190 497 190 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) Closet
    set {floorItems(Closet)} $i
    $w create text 502.5 190 -text Closet -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 476 237 476 206 513 206 513 254 488 254 488 237 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) WShower
    set {floorItems(WShower)} $i
    $w create text 494.5 230 -text WShower -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 486 131 558 131 558 135 724 135 724 166 697 166 697 275 553 275 531 254 515 254 515 174 503 174 503 161 486 161 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 130
    set {floorItems(130)} $i
    $w create text 638.5 205 -text 130 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 308 242 339 242 339 248 342 248 342 246 397 246 397 276 393 276 393 309 300 309 300 248 308 248 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 102
    set {floorItems(102)} $i
    $w create text 367.5 278.5 -text 102 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 397 255 486 255 486 276 397 276 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 128
    set {floorItems(128)} $i
    $w create text 441.5 265.5 -text 128 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 510 309 486 309 486 255 530 255 552 277 561 277 561 325 510 325 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 129
    set {floorItems(129)} $i
    $w create text 535.5 293 -text 129 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 696 281 740 281 740 387 642 387 642 389 561 389 561 277 696 277 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 133
    set {floorItems(133)} $i
    $w create text 628.5 335 -text 133 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 742 387 742 281 800 281 800 387 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 132
    set {floorItems(132)} $i
    $w create text 771 334 -text 132 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 800 168 800 280 699 280 699 168 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 134
    set {floorItems(134)} $i
    $w create text 749.5 224 -text 134 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 726 131 726 166 800 166 800 131 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 135
    set {floorItems(135)} $i
    $w create text 763 148.5 -text 135 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 340 360 335 363 331 365 326 366 304 366 304 312 396 312 396 288 400 288 404 288 409 290 413 292 418 297 421 302 422 309 421 318 417 325 411 330 405 332 397 333 344 333 340 334 336 336 335 338 332 342 331 347 332 351 334 354 336 357 341 359 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) {Ramona Stair}
    set {floorItems(Ramona Stair)} $i
    $w create text 368 323 -text {Ramona Stair} -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 30 23 30 5 93 5 98 5 104 7 110 10 116 16 119 20 122 28 123 32 123 68 220 68 220 87 90 87 90 23 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) {University Stair}
    set {floorItems(University Stair)} $i
    $w create text 155 77.5 -text {University Stair} -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 282 37 295 40 312 49 323 56 337 70 352 56 358 48 363 39 365 29 348 25 335 22 321 14 300 5 283 1 260 0 246 0 242 2 236 4 231 8 227 13 223 17 221 22 220 34 260 34 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) {Plaza Stair}
    set {floorItems(Plaza Stair)} $i
    $w create text 317.5 28.5 -text {Plaza Stair} -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 220 34 260 34 282 37 295 40 312 49 323 56 337 70 350 83 365 94 377 100 386 104 386 128 220 128 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) {Plaza Deck}
    set {floorItems(Plaza Deck)} $i
    $w create text 303 81 -text {Plaza Deck} -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 257 336 77 336 6 336 6 301 77 301 77 310 257 310 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 106
    set {floorItems(106)} $i
    $w create text 131.5 318.5 -text 106 -fill $color -anchor c -tags {floor1 label}
    set i [$w create polygon 146 110 162 110 162 91 130 91 130 115 95 115 95 128 114 128 114 151 157 151 157 153 112 153 112 130 97 130 97 168 175 168 175 131 146 131 -fill {} -outline {} -tags {floor1 room}]
    set floorLabels($i) 119
    set {floorItems(119)} $i
    $w create text 143.5 133 -text 119 -fill $color -anchor c -tags {floor1 label}
    $w create line 155 191 155 189 -fill $color -tags {floor1 wall}
    $w create line 155 177 155 169 -fill $color -tags {floor1 wall}
    $w create line 96 129 96 169 -fill $color -tags {floor1 wall}
    $w create line 78 169 176 169 -fill $color -tags {floor1 wall}
    $w create line 176 247 176 129 -fill $color -tags {floor1 wall}
    $w create line 340 206 307 206 -fill $color -tags {floor1 wall}
    $w create line 340 187 340 170 -fill $color -tags {floor1 wall}
    $w create line 340 210 340 201 -fill $color -tags {floor1 wall}
    $w create line 340 247 340 224 -fill $color -tags {floor1 wall}
    $w create line 340 241 307 241 -fill $color -tags {floor1 wall}
    $w create line 376 246 376 170 -fill $color -tags {floor1 wall}
    $w create line 307 247 307 170 -fill $color -tags {floor1 wall}
    $w create line 376 170 307 170 -fill $color -tags {floor1 wall}
    $w create line 315 129 315 170 -fill $color -tags {floor1 wall}
    $w create line 147 129 176 129 -fill $color -tags {floor1 wall}
    $w create line 202 133 176 133 -fill $color -tags {floor1 wall}
    $w create line 398 129 315 129 -fill $color -tags {floor1 wall}
    $w create line 258 352 258 387 -fill $color -tags {floor1 wall}
    $w create line 60 387 60 391 -fill $color -tags {floor1 wall}
    $w create line 0 337 0 391 -fill $color -tags {floor1 wall}
    $w create line 60 391 0 391 -fill $color -tags {floor1 wall}
    $w create line 3 114 3 337 -fill $color -tags {floor1 wall}
    $w create line 258 387 60 387 -fill $color -tags {floor1 wall}
    $w create line 52 237 52 273 -fill $color -tags {floor1 wall}
    $w create line 52 189 52 225 -fill $color -tags {floor1 wall}
    $w create line 52 140 52 177 -fill $color -tags {floor1 wall}
    $w create line 395 306 395 311 -fill $color -tags {floor1 wall}
    $w create line 531 254 398 254 -fill $color -tags {floor1 wall}
    $w create line 475 178 475 238 -fill $color -tags {floor1 wall}
    $w create line 502 162 398 162 -fill $color -tags {floor1 wall}
    $w create line 398 129 398 188 -fill $color -tags {floor1 wall}
    $w create line 383 188 376 188 -fill $color -tags {floor1 wall}
    $w create line 408 188 408 194 -fill $color -tags {floor1 wall}
    $w create line 398 227 398 254 -fill $color -tags {floor1 wall}
    $w create line 408 227 398 227 -fill $color -tags {floor1 wall}
    $w create line 408 222 408 227 -fill $color -tags {floor1 wall}
    $w create line 408 206 408 210 -fill $color -tags {floor1 wall}
    $w create line 408 208 475 208 -fill $color -tags {floor1 wall}
    $w create line 484 278 484 311 -fill $color -tags {floor1 wall}
    $w create line 484 311 508 311 -fill $color -tags {floor1 wall}
    $w create line 508 327 508 311 -fill $color -tags {floor1 wall}
    $w create line 559 327 508 327 -fill $color -tags {floor1 wall}
    $w create line 644 391 559 391 -fill $color -tags {floor1 wall}
    $w create line 644 389 644 391 -fill $color -tags {floor1 wall}
    $w create line 514 205 475 205 -fill $color -tags {floor1 wall}
    $w create line 496 189 496 187 -fill $color -tags {floor1 wall}
    $w create line 559 129 484 129 -fill $color -tags {floor1 wall}
    $w create line 484 162 484 129 -fill $color -tags {floor1 wall}
    $w create line 725 133 559 133 -fill $color -tags {floor1 wall}
    $w create line 559 129 559 133 -fill $color -tags {floor1 wall}
    $w create line 725 149 725 167 -fill $color -tags {floor1 wall}
    $w create line 725 129 802 129 -fill $color -tags {floor1 wall}
    $w create line 802 389 802 129 -fill $color -tags {floor1 wall}
    $w create line 739 167 802 167 -fill $color -tags {floor1 wall}
    $w create line 396 188 408 188 -fill $color -tags {floor1 wall}
    $w create line 0 337 9 337 -fill $color -tags {floor1 wall}
    $w create line 58 337 21 337 -fill $color -tags {floor1 wall}
    $w create line 43 391 43 337 -fill $color -tags {floor1 wall}
    $w create line 105 337 75 337 -fill $color -tags {floor1 wall}
    $w create line 91 387 91 337 -fill $color -tags {floor1 wall}
    $w create line 154 337 117 337 -fill $color -tags {floor1 wall}
    $w create line 139 387 139 337 -fill $color -tags {floor1 wall}
    $w create line 227 337 166 337 -fill $color -tags {floor1 wall}
    $w create line 258 337 251 337 -fill $color -tags {floor1 wall}
    $w create line 258 328 302 328 -fill $color -tags {floor1 wall}
    $w create line 302 355 302 311 -fill $color -tags {floor1 wall}
    $w create line 395 311 302 311 -fill $color -tags {floor1 wall}
    $w create line 484 278 395 278 -fill $color -tags {floor1 wall}
    $w create line 395 294 395 278 -fill $color -tags {floor1 wall}
    $w create line 473 278 473 275 -fill $color -tags {floor1 wall}
    $w create line 473 256 473 254 -fill $color -tags {floor1 wall}
    $w create line 533 257 531 254 -fill $color -tags {floor1 wall}
    $w create line 553 276 551 274 -fill $color -tags {floor1 wall}
    $w create line 698 276 553 276 -fill $color -tags {floor1 wall}
    $w create line 559 391 559 327 -fill $color -tags {floor1 wall}
    $w create line 802 389 644 389 -fill $color -tags {floor1 wall}
    $w create line 741 314 741 389 -fill $color -tags {floor1 wall}
    $w create line 698 280 698 167 -fill $color -tags {floor1 wall}
    $w create line 707 280 698 280 -fill $color -tags {floor1 wall}
    $w create line 802 280 731 280 -fill $color -tags {floor1 wall}
    $w create line 741 280 741 302 -fill $color -tags {floor1 wall}
    $w create line 698 167 727 167 -fill $color -tags {floor1 wall}
    $w create line 725 137 725 129 -fill $color -tags {floor1 wall}
    $w create line 514 254 514 175 -fill $color -tags {floor1 wall}
    $w create line 496 175 514 175 -fill $color -tags {floor1 wall}
    $w create line 502 175 502 162 -fill $color -tags {floor1 wall}
    $w create line 475 166 475 162 -fill $color -tags {floor1 wall}
    $w create line 496 176 496 175 -fill $color -tags {floor1 wall}
    $w create line 491 189 496 189 -fill $color -tags {floor1 wall}
    $w create line 491 205 491 189 -fill $color -tags {floor1 wall}
    $w create line 487 238 475 238 -fill $color -tags {floor1 wall}
    $w create line 487 240 487 238 -fill $color -tags {floor1 wall}
    $w create line 487 252 487 254 -fill $color -tags {floor1 wall}
    $w create line 315 133 304 133 -fill $color -tags {floor1 wall}
    $w create line 256 133 280 133 -fill $color -tags {floor1 wall}
    $w create line 78 247 270 247 -fill $color -tags {floor1 wall}
    $w create line 307 247 294 247 -fill $color -tags {floor1 wall}
    $w create line 214 133 232 133 -fill $color -tags {floor1 wall}
    $w create line 217 247 217 266 -fill $color -tags {floor1 wall}
    $w create line 217 309 217 291 -fill $color -tags {floor1 wall}
    $w create line 217 309 172 309 -fill $color -tags {floor1 wall}
    $w create line 154 309 148 309 -fill $color -tags {floor1 wall}
    $w create line 175 300 175 309 -fill $color -tags {floor1 wall}
    $w create line 151 300 175 300 -fill $color -tags {floor1 wall}
    $w create line 151 247 151 309 -fill $color -tags {floor1 wall}
    $w create line 78 237 78 265 -fill $color -tags {floor1 wall}
    $w create line 78 286 78 309 -fill $color -tags {floor1 wall}
    $w create line 106 309 78 309 -fill $color -tags {floor1 wall}
    $w create line 130 309 125 309 -fill $color -tags {floor1 wall}
    $w create line 99 309 99 247 -fill $color -tags {floor1 wall}
    $w create line 127 299 99 299 -fill $color -tags {floor1 wall}
    $w create line 127 309 127 299 -fill $color -tags {floor1 wall}
    $w create line 155 191 137 191 -fill $color -tags {floor1 wall}
    $w create line 137 169 137 191 -fill $color -tags {floor1 wall}
    $w create line 78 171 78 169 -fill $color -tags {floor1 wall}
    $w create line 78 190 78 218 -fill $color -tags {floor1 wall}
    $w create line 86 192 86 169 -fill $color -tags {floor1 wall}
    $w create line 86 192 78 192 -fill $color -tags {floor1 wall}
    $w create line 52 301 3 301 -fill $color -tags {floor1 wall}
    $w create line 52 286 52 301 -fill $color -tags {floor1 wall}
    $w create line 52 252 3 252 -fill $color -tags {floor1 wall}
    $w create line 52 203 3 203 -fill $color -tags {floor1 wall}
    $w create line 3 156 52 156 -fill $color -tags {floor1 wall}
    $w create line 8 25 8 114 -fill $color -tags {floor1 wall}
    $w create line 63 114 3 114 -fill $color -tags {floor1 wall}
    $w create line 75 114 97 114 -fill $color -tags {floor1 wall}
    $w create line 108 114 129 114 -fill $color -tags {floor1 wall}
    $w create line 129 114 129 89 -fill $color -tags {floor1 wall}
    $w create line 52 114 52 128 -fill $color -tags {floor1 wall}
    $w create line 132 89 88 89 -fill $color -tags {floor1 wall}
    $w create line 88 25 88 89 -fill $color -tags {floor1 wall}
    $w create line 88 114 88 89 -fill $color -tags {floor1 wall}
    $w create line 218 89 144 89 -fill $color -tags {floor1 wall}
    $w create line 147 111 147 129 -fill $color -tags {floor1 wall}
    $w create line 162 111 147 111 -fill $color -tags {floor1 wall}
    $w create line 162 109 162 111 -fill $color -tags {floor1 wall}
    $w create line 162 96 162 89 -fill $color -tags {floor1 wall}
    $w create line 218 89 218 94 -fill $color -tags {floor1 wall}
    $w create line 218 89 218 119 -fill $color -tags {floor1 wall}
    $w create line 8 25 88 25 -fill $color -tags {floor1 wall}
    $w create line 258 337 258 328 -fill $color -tags {floor1 wall}
    $w create line 113 129 96 129 -fill $color -tags {floor1 wall}
    $w create line 302 355 258 355 -fill $color -tags {floor1 wall}
    $w create line 386 104 386 129 -fill $color -tags {floor1 wall}
    $w create line 377 100 386 104 -fill $color -tags {floor1 wall}
    $w create line 365 94 377 100 -fill $color -tags {floor1 wall}
    $w create line 350 83 365 94 -fill $color -tags {floor1 wall}
    $w create line 337 70 350 83 -fill $color -tags {floor1 wall}
    $w create line 337 70 323 56 -fill $color -tags {floor1 wall}
    $w create line 312 49 323 56 -fill $color -tags {floor1 wall}
    $w create line 295 40 312 49 -fill $color -tags {floor1 wall}
    $w create line 282 37 295 40 -fill $color -tags {floor1 wall}
    $w create line 260 34 282 37 -fill $color -tags {floor1 wall}
    $w create line 253 34 260 34 -fill $color -tags {floor1 wall}
    $w create line 386 128 386 104 -fill $color -tags {floor1 wall}
    $w create line 113 152 156 152 -fill $color -tags {floor1 wall}
    $w create line 113 152 156 152 -fill $color -tags {floor1 wall}
    $w create line 113 152 113 129 -fill $color -tags {floor1 wall}
}

# fg2 --
# This procedure represents part of the floorplan database.  When
# invoked, it instantiates the foreground information for the second
# floor (office outlines and numbers).
#
# Arguments:
# w -		The canvas window.
# color -	Color to use for drawing foreground information.

proc fg2 {w color} {
    global floorLabels floorItems
    set i [$w create polygon 748 188 755 188 755 205 758 205 758 222 800 222 800 168 748 168 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 238
    set {floorItems(238)} $i
    $w create text 774 195 -text 238 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 726 188 746 188 746 166 800 166 800 131 726 131 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 237
    set {floorItems(237)} $i
    $w create text 763 148.5 -text 237 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 497 187 497 204 559 204 559 324 641 324 643 324 643 291 641 291 641 205 696 205 696 291 694 291 694 314 715 314 715 291 715 205 755 205 755 190 724 190 724 187 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 246
    set {floorItems(246)} $i
    $w create text 600 264 -text 246 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 694 279 643 279 643 314 694 314 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 247
    set {floorItems(247)} $i
    $w create text 668.5 296.5 -text 247 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 232 250 308 250 308 242 339 242 339 246 397 246 397 255 476 255 476 250 482 250 559 250 559 274 482 274 482 278 396 278 396 274 232 274 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 202
    set {floorItems(202)} $i
    $w create text 285.5 260 -text 202 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 53 228 53 338 176 338 233 338 233 196 306 196 306 180 175 180 175 169 156 169 156 196 176 196 176 228 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 206
    set {floorItems(206)} $i
    $w create text 143 267 -text 206 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 51 277 6 277 6 338 51 338 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 212
    set {floorItems(212)} $i
    $w create text 28.5 307.5 -text 212 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 557 276 486 276 486 309 510 309 510 325 557 325 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 245
    set {floorItems(245)} $i
    $w create text 521.5 300.5 -text 245 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 560 389 599 389 599 326 560 326 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 244
    set {floorItems(244)} $i
    $w create text 579.5 357.5 -text 244 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 601 389 601 326 643 326 643 389 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 243
    set {floorItems(243)} $i
    $w create text 622 357.5 -text 243 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 688 316 645 316 645 365 688 365 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 242
    set {floorItems(242)} $i
    $w create text 666.5 340.5 -text 242 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 802 367 759 367 759 226 802 226 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) {Barbecue Deck}
    set {floorItems(Barbecue Deck)} $i
    $w create text 780.5 296.5 -text {Barbecue Deck} -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 755 262 755 314 717 314 717 262 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 240
    set {floorItems(240)} $i
    $w create text 736 288 -text 240 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 755 316 689 316 689 365 755 365 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 241
    set {floorItems(241)} $i
    $w create text 722 340.5 -text 241 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 755 206 717 206 717 261 755 261 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 239
    set {floorItems(239)} $i
    $w create text 736 233.5 -text 239 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 695 277 643 277 643 206 695 206 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 248
    set {floorItems(248)} $i
    $w create text 669 241.5 -text 248 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 676 135 676 185 724 185 724 135 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 236
    set {floorItems(236)} $i
    $w create text 700 160 -text 236 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 675 135 635 135 635 145 628 145 628 185 675 185 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 235
    set {floorItems(235)} $i
    $w create text 651.5 160 -text 235 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 626 143 633 143 633 135 572 135 572 143 579 143 579 185 626 185 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 234
    set {floorItems(234)} $i
    $w create text 606 160 -text 234 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 557 135 571 135 571 145 578 145 578 185 527 185 527 131 557 131 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 233
    set {floorItems(233)} $i
    $w create text 552.5 158 -text 233 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 476 249 557 249 557 205 476 205 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 230
    set {floorItems(230)} $i
    $w create text 516.5 227 -text 230 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 476 164 486 164 486 131 525 131 525 185 476 185 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 232
    set {floorItems(232)} $i
    $w create text 500.5 158 -text 232 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 476 186 495 186 495 204 476 204 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 229
    set {floorItems(229)} $i
    $w create text 485.5 195 -text 229 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 474 207 409 207 409 187 399 187 399 164 474 164 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 227
    set {floorItems(227)} $i
    $w create text 436.5 185.5 -text 227 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 399 228 399 253 474 253 474 209 409 209 409 228 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 228
    set {floorItems(228)} $i
    $w create text 436.5 231 -text 228 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 397 246 397 226 407 226 407 189 377 189 377 246 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 226
    set {floorItems(226)} $i
    $w create text 392 217.5 -text 226 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 377 169 316 169 316 131 397 131 397 188 377 188 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 225
    set {floorItems(225)} $i
    $w create text 356.5 150 -text 225 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 234 198 306 198 306 249 234 249 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 224
    set {floorItems(224)} $i
    $w create text 270 223.5 -text 224 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 270 179 306 179 306 170 314 170 314 135 270 135 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 223
    set {floorItems(223)} $i
    $w create text 292 157 -text 223 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 268 179 221 179 221 135 268 135 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 222
    set {floorItems(222)} $i
    $w create text 244.5 157 -text 222 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 177 179 219 179 219 135 177 135 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 221
    set {floorItems(221)} $i
    $w create text 198 157 -text 221 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 299 327 349 327 349 284 341 284 341 276 299 276 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 204
    set {floorItems(204)} $i
    $w create text 324 301.5 -text 204 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 234 276 297 276 297 327 257 327 257 338 234 338 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 205
    set {floorItems(205)} $i
    $w create text 265.5 307 -text 205 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 256 385 256 340 212 340 212 385 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 207
    set {floorItems(207)} $i
    $w create text 234 362.5 -text 207 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 210 340 164 340 164 385 210 385 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 208
    set {floorItems(208)} $i
    $w create text 187 362.5 -text 208 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 115 340 162 340 162 385 115 385 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 209
    set {floorItems(209)} $i
    $w create text 138.5 362.5 -text 209 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 89 228 89 156 53 156 53 228 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 217
    set {floorItems(217)} $i
    $w create text 71 192 -text 217 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 89 169 97 169 97 190 89 190 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 217A
    set {floorItems(217A)} $i
    $w create text 93 179.5 -text 217A -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 89 156 89 168 95 168 95 135 53 135 53 156 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 216
    set {floorItems(216)} $i
    $w create text 71 145.5 -text 216 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 51 179 51 135 6 135 6 179 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 215
    set {floorItems(215)} $i
    $w create text 28.5 157 -text 215 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 51 227 6 227 6 180 51 180 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 214
    set {floorItems(214)} $i
    $w create text 28.5 203.5 -text 214 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 51 275 6 275 6 229 51 229 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 213
    set {floorItems(213)} $i
    $w create text 28.5 252 -text 213 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 114 340 67 340 67 385 114 385 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 210
    set {floorItems(210)} $i
    $w create text 90.5 362.5 -text 210 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 59 389 59 385 65 385 65 340 1 340 1 389 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 211
    set {floorItems(211)} $i
    $w create text 33 364.5 -text 211 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 393 309 350 309 350 282 342 282 342 276 393 276 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 203
    set {floorItems(203)} $i
    $w create text 367.5 292.5 -text 203 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 99 191 91 191 91 226 174 226 174 198 154 198 154 192 109 192 109 169 99 169 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 220
    set {floorItems(220)} $i
    $w create text 132.5 208.5 -text 220 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 339 205 307 205 307 171 339 171 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) {Priv Lift2}
    set {floorItems(Priv Lift2)} $i
    $w create text 323 188 -text {Priv Lift2} -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 307 240 339 240 339 206 307 206 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) {Pub Lift 2}
    set {floorItems(Pub Lift 2)} $i
    $w create text 323 223 -text {Pub Lift 2} -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 175 168 97 168 97 131 175 131 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 218
    set {floorItems(218)} $i
    $w create text 136 149.5 -text 218 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 154 191 111 191 111 169 154 169 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 219
    set {floorItems(219)} $i
    $w create text 132.5 180 -text 219 -fill $color -anchor c -tags {floor2 label}
    set i [$w create polygon 375 246 375 172 341 172 341 246 -fill {} -outline {} -tags {floor2 room}]
    set floorLabels($i) 201
    set {floorItems(201)} $i
    $w create text 358 209 -text 201 -fill $color -anchor c -tags {floor2 label}
    $w create line 641 186 678 186 -fill $color -tags {floor2 wall}
    $w create line 757 350 757 367 -fill $color -tags {floor2 wall}
    $w create line 634 133 634 144 -fill $color -tags {floor2 wall}
    $w create line 634 144 627 144 -fill $color -tags {floor2 wall}
    $w create line 572 133 572 144 -fill $color -tags {floor2 wall}
    $w create line 572 144 579 144 -fill $color -tags {floor2 wall}
    $w create line 398 129 398 162 -fill $color -tags {floor2 wall}
    $w create line 174 197 175 197 -fill $color -tags {floor2 wall}
    $w create line 175 197 175 227 -fill $color -tags {floor2 wall}
    $w create line 757 206 757 221 -fill $color -tags {floor2 wall}
    $w create line 396 188 408 188 -fill $color -tags {floor2 wall}
    $w create line 727 189 725 189 -fill $color -tags {floor2 wall}
    $w create line 747 167 802 167 -fill $color -tags {floor2 wall}
    $w create line 747 167 747 189 -fill $color -tags {floor2 wall}
    $w create line 755 189 739 189 -fill $color -tags {floor2 wall}
    $w create line 769 224 757 224 -fill $color -tags {floor2 wall}
    $w create line 802 224 802 129 -fill $color -tags {floor2 wall}
    $w create line 802 129 725 129 -fill $color -tags {floor2 wall}
    $w create line 725 189 725 129 -fill $color -tags {floor2 wall}
    $w create line 725 186 690 186 -fill $color -tags {floor2 wall}
    $w create line 676 133 676 186 -fill $color -tags {floor2 wall}
    $w create line 627 144 627 186 -fill $color -tags {floor2 wall}
    $w create line 629 186 593 186 -fill $color -tags {floor2 wall}
    $w create line 579 144 579 186 -fill $color -tags {floor2 wall}
    $w create line 559 129 559 133 -fill $color -tags {floor2 wall}
    $w create line 725 133 559 133 -fill $color -tags {floor2 wall}
    $w create line 484 162 484 129 -fill $color -tags {floor2 wall}
    $w create line 559 129 484 129 -fill $color -tags {floor2 wall}
    $w create line 526 129 526 186 -fill $color -tags {floor2 wall}
    $w create line 540 186 581 186 -fill $color -tags {floor2 wall}
    $w create line 528 186 523 186 -fill $color -tags {floor2 wall}
    $w create line 511 186 475 186 -fill $color -tags {floor2 wall}
    $w create line 496 190 496 186 -fill $color -tags {floor2 wall}
    $w create line 496 205 496 202 -fill $color -tags {floor2 wall}
    $w create line 475 205 527 205 -fill $color -tags {floor2 wall}
    $w create line 558 205 539 205 -fill $color -tags {floor2 wall}
    $w create line 558 205 558 249 -fill $color -tags {floor2 wall}
    $w create line 558 249 475 249 -fill $color -tags {floor2 wall}
    $w create line 662 206 642 206 -fill $color -tags {floor2 wall}
    $w create line 695 206 675 206 -fill $color -tags {floor2 wall}
    $w create line 695 278 642 278 -fill $color -tags {floor2 wall}
    $w create line 642 291 642 206 -fill $color -tags {floor2 wall}
    $w create line 695 291 695 206 -fill $color -tags {floor2 wall}
    $w create line 716 208 716 206 -fill $color -tags {floor2 wall}
    $w create line 757 206 716 206 -fill $color -tags {floor2 wall}
    $w create line 757 221 757 224 -fill $color -tags {floor2 wall}
    $w create line 793 224 802 224 -fill $color -tags {floor2 wall}
    $w create line 757 262 716 262 -fill $color -tags {floor2 wall}
    $w create line 716 220 716 264 -fill $color -tags {floor2 wall}
    $w create line 716 315 716 276 -fill $color -tags {floor2 wall}
    $w create line 757 315 703 315 -fill $color -tags {floor2 wall}
    $w create line 757 325 757 224 -fill $color -tags {floor2 wall}
    $w create line 757 367 644 367 -fill $color -tags {floor2 wall}
    $w create line 689 367 689 315 -fill $color -tags {floor2 wall}
    $w create line 647 315 644 315 -fill $color -tags {floor2 wall}
    $w create line 659 315 691 315 -fill $color -tags {floor2 wall}
    $w create line 600 325 600 391 -fill $color -tags {floor2 wall}
    $w create line 627 325 644 325 -fill $color -tags {floor2 wall}
    $w create line 644 391 644 315 -fill $color -tags {floor2 wall}
    $w create line 615 325 575 325 -fill $color -tags {floor2 wall}
    $w create line 644 391 558 391 -fill $color -tags {floor2 wall}
    $w create line 563 325 558 325 -fill $color -tags {floor2 wall}
    $w create line 558 391 558 314 -fill $color -tags {floor2 wall}
    $w create line 558 327 508 327 -fill $color -tags {floor2 wall}
    $w create line 558 275 484 275 -fill $color -tags {floor2 wall}
    $w create line 558 302 558 275 -fill $color -tags {floor2 wall}
    $w create line 508 327 508 311 -fill $color -tags {floor2 wall}
    $w create line 484 311 508 311 -fill $color -tags {floor2 wall}
    $w create line 484 275 484 311 -fill $color -tags {floor2 wall}
    $w create line 475 208 408 208 -fill $color -tags {floor2 wall}
    $w create line 408 206 408 210 -fill $color -tags {floor2 wall}
    $w create line 408 222 408 227 -fill $color -tags {floor2 wall}
    $w create line 408 227 398 227 -fill $color -tags {floor2 wall}
    $w create line 398 227 398 254 -fill $color -tags {floor2 wall}
    $w create line 408 188 408 194 -fill $color -tags {floor2 wall}
    $w create line 383 188 376 188 -fill $color -tags {floor2 wall}
    $w create line 398 188 398 162 -fill $color -tags {floor2 wall}
    $w create line 398 162 484 162 -fill $color -tags {floor2 wall}
    $w create line 475 162 475 254 -fill $color -tags {floor2 wall}
    $w create line 398 254 475 254 -fill $color -tags {floor2 wall}
    $w create line 484 280 395 280 -fill $color -tags {floor2 wall}
    $w create line 395 311 395 275 -fill $color -tags {floor2 wall}
    $w create line 307 197 293 197 -fill $color -tags {floor2 wall}
    $w create line 278 197 233 197 -fill $color -tags {floor2 wall}
    $w create line 233 197 233 249 -fill $color -tags {floor2 wall}
    $w create line 307 179 284 179 -fill $color -tags {floor2 wall}
    $w create line 233 249 278 249 -fill $color -tags {floor2 wall}
    $w create line 269 179 269 133 -fill $color -tags {floor2 wall}
    $w create line 220 179 220 133 -fill $color -tags {floor2 wall}
    $w create line 155 191 110 191 -fill $color -tags {floor2 wall}
    $w create line 90 190 98 190 -fill $color -tags {floor2 wall}
    $w create line 98 169 98 190 -fill $color -tags {floor2 wall}
    $w create line 52 133 52 165 -fill $color -tags {floor2 wall}
    $w create line 52 214 52 177 -fill $color -tags {floor2 wall}
    $w create line 52 226 52 262 -fill $color -tags {floor2 wall}
    $w create line 52 274 52 276 -fill $color -tags {floor2 wall}
    $w create line 234 275 234 339 -fill $color -tags {floor2 wall}
    $w create line 226 339 258 339 -fill $color -tags {floor2 wall}
    $w create line 211 387 211 339 -fill $color -tags {floor2 wall}
    $w create line 214 339 177 339 -fill $color -tags {floor2 wall}
    $w create line 258 387 60 387 -fill $color -tags {floor2 wall}
    $w create line 3 133 3 339 -fill $color -tags {floor2 wall}
    $w create line 165 339 129 339 -fill $color -tags {floor2 wall}
    $w create line 117 339 80 339 -fill $color -tags {floor2 wall}
    $w create line 68 339 59 339 -fill $color -tags {floor2 wall}
    $w create line 0 339 46 339 -fill $color -tags {floor2 wall}
    $w create line 60 391 0 391 -fill $color -tags {floor2 wall}
    $w create line 0 339 0 391 -fill $color -tags {floor2 wall}
    $w create line 60 387 60 391 -fill $color -tags {floor2 wall}
    $w create line 258 329 258 387 -fill $color -tags {floor2 wall}
    $w create line 350 329 258 329 -fill $color -tags {floor2 wall}
    $w create line 395 311 350 311 -fill $color -tags {floor2 wall}
    $w create line 398 129 315 129 -fill $color -tags {floor2 wall}
    $w create line 176 133 315 133 -fill $color -tags {floor2 wall}
    $w create line 176 129 96 129 -fill $color -tags {floor2 wall}
    $w create line 3 133 96 133 -fill $color -tags {floor2 wall}
    $w create line 66 387 66 339 -fill $color -tags {floor2 wall}
    $w create line 115 387 115 339 -fill $color -tags {floor2 wall}
    $w create line 163 387 163 339 -fill $color -tags {floor2 wall}
    $w create line 234 275 276 275 -fill $color -tags {floor2 wall}
    $w create line 288 275 309 275 -fill $color -tags {floor2 wall}
    $w create line 298 275 298 329 -fill $color -tags {floor2 wall}
    $w create line 341 283 350 283 -fill $color -tags {floor2 wall}
    $w create line 321 275 341 275 -fill $color -tags {floor2 wall}
    $w create line 375 275 395 275 -fill $color -tags {floor2 wall}
    $w create line 315 129 315 170 -fill $color -tags {floor2 wall}
    $w create line 376 170 307 170 -fill $color -tags {floor2 wall}
    $w create line 307 250 307 170 -fill $color -tags {floor2 wall}
    $w create line 376 245 376 170 -fill $color -tags {floor2 wall}
    $w create line 340 241 307 241 -fill $color -tags {floor2 wall}
    $w create line 340 245 340 224 -fill $color -tags {floor2 wall}
    $w create line 340 210 340 201 -fill $color -tags {floor2 wall}
    $w create line 340 187 340 170 -fill $color -tags {floor2 wall}
    $w create line 340 206 307 206 -fill $color -tags {floor2 wall}
    $w create line 293 250 307 250 -fill $color -tags {floor2 wall}
    $w create line 271 179 238 179 -fill $color -tags {floor2 wall}
    $w create line 226 179 195 179 -fill $color -tags {floor2 wall}
    $w create line 176 129 176 179 -fill $color -tags {floor2 wall}
    $w create line 182 179 176 179 -fill $color -tags {floor2 wall}
    $w create line 174 169 176 169 -fill $color -tags {floor2 wall}
    $w create line 162 169 90 169 -fill $color -tags {floor2 wall}
    $w create line 96 169 96 129 -fill $color -tags {floor2 wall}
    $w create line 175 227 90 227 -fill $color -tags {floor2 wall}
    $w create line 90 190 90 227 -fill $color -tags {floor2 wall}
    $w create line 52 179 3 179 -fill $color -tags {floor2 wall}
    $w create line 52 228 3 228 -fill $color -tags {floor2 wall}
    $w create line 52 276 3 276 -fill $color -tags {floor2 wall}
    $w create line 155 177 155 169 -fill $color -tags {floor2 wall}
    $w create line 110 191 110 169 -fill $color -tags {floor2 wall}
    $w create line 155 189 155 197 -fill $color -tags {floor2 wall}
    $w create line 350 283 350 329 -fill $color -tags {floor2 wall}
    $w create line 162 197 155 197 -fill $color -tags {floor2 wall}
    $w create line 341 275 341 283 -fill $color -tags {floor2 wall}
}

# fg3 --
# This procedure represents part of the floorplan database.  When
# invoked, it instantiates the foreground information for the third
# floor (office outlines and numbers).
#
# Arguments:
# w -		The canvas window.
# color -	Color to use for drawing foreground information.

proc fg3 {w color} {
    global floorLabels floorItems
    set i [$w create polygon 89 228 89 180 70 180 70 228 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 316
    set {floorItems(316)} $i
    $w create text 79.5 204 -text 316 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 115 368 162 368 162 323 115 323 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 309
    set {floorItems(309)} $i
    $w create text 138.5 345.5 -text 309 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 164 323 164 368 211 368 211 323 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 308
    set {floorItems(308)} $i
    $w create text 187.5 345.5 -text 308 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 256 368 212 368 212 323 256 323 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 307
    set {floorItems(307)} $i
    $w create text 234 345.5 -text 307 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 244 276 297 276 297 327 260 327 260 321 244 321 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 305
    set {floorItems(305)} $i
    $w create text 270.5 301.5 -text 305 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 251 219 251 203 244 203 244 219 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 324B
    set {floorItems(324B)} $i
    $w create text 247.5 211 -text 324B -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 251 249 244 249 244 232 251 232 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 324A
    set {floorItems(324A)} $i
    $w create text 247.5 240.5 -text 324A -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 223 135 223 179 177 179 177 135 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 320
    set {floorItems(320)} $i
    $w create text 200 157 -text 320 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 114 368 114 323 67 323 67 368 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 310
    set {floorItems(310)} $i
    $w create text 90.5 345.5 -text 310 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 23 277 23 321 68 321 68 277 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 312
    set {floorItems(312)} $i
    $w create text 45.5 299 -text 312 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 23 229 68 229 68 275 23 275 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 313
    set {floorItems(313)} $i
    $w create text 45.5 252 -text 313 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 68 227 23 227 23 180 68 180 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 314
    set {floorItems(314)} $i
    $w create text 45.5 203.5 -text 314 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 95 179 95 135 23 135 23 179 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 315
    set {floorItems(315)} $i
    $w create text 59 157 -text 315 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 99 226 99 204 91 204 91 226 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 316B
    set {floorItems(316B)} $i
    $w create text 95 215 -text 316B -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 91 202 99 202 99 180 91 180 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 316A
    set {floorItems(316A)} $i
    $w create text 95 191 -text 316A -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 97 169 109 169 109 192 154 192 154 198 174 198 174 226 101 226 101 179 97 179 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 319
    set {floorItems(319)} $i
    $w create text 141.5 209 -text 319 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 65 368 58 368 58 389 1 389 1 333 23 333 23 323 65 323 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 311
    set {floorItems(311)} $i
    $w create text 29.5 361 -text 311 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 154 191 111 191 111 169 154 169 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 318
    set {floorItems(318)} $i
    $w create text 132.5 180 -text 318 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 175 168 97 168 97 131 175 131 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 317
    set {floorItems(317)} $i
    $w create text 136 149.5 -text 317 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 274 194 274 221 306 221 306 194 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 323
    set {floorItems(323)} $i
    $w create text 290 207.5 -text 323 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 306 222 274 222 274 249 306 249 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 325
    set {floorItems(325)} $i
    $w create text 290 235.5 -text 325 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 263 179 224 179 224 135 263 135 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 321
    set {floorItems(321)} $i
    $w create text 243.5 157 -text 321 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 314 169 306 169 306 192 273 192 264 181 264 135 314 135 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 322
    set {floorItems(322)} $i
    $w create text 293.5 163.5 -text 322 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 307 240 339 240 339 206 307 206 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) {Pub Lift3}
    set {floorItems(Pub Lift3)} $i
    $w create text 323 223 -text {Pub Lift3} -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 339 205 307 205 307 171 339 171 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) {Priv Lift3}
    set {floorItems(Priv Lift3)} $i
    $w create text 323 188 -text {Priv Lift3} -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 350 284 376 284 376 276 397 276 397 309 350 309 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 303
    set {floorItems(303)} $i
    $w create text 373.5 292.5 -text 303 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 272 203 272 249 252 249 252 230 244 230 244 221 252 221 252 203 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 324
    set {floorItems(324)} $i
    $w create text 262 226 -text 324 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 299 276 299 327 349 327 349 284 341 284 341 276 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 304
    set {floorItems(304)} $i
    $w create text 324 301.5 -text 304 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 375 246 375 172 341 172 341 246 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 301
    set {floorItems(301)} $i
    $w create text 358 209 -text 301 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 397 246 377 246 377 185 397 185 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 327
    set {floorItems(327)} $i
    $w create text 387 215.5 -text 327 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 316 131 316 169 377 169 377 185 397 185 397 131 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 326
    set {floorItems(326)} $i
    $w create text 356.5 150 -text 326 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 308 251 242 251 242 274 342 274 342 282 375 282 375 274 397 274 397 248 339 248 339 242 308 242 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 302
    set {floorItems(302)} $i
    $w create text 319.5 261 -text 302 -fill $color -anchor c -tags {floor3 label}
    set i [$w create polygon 70 321 242 321 242 200 259 200 259 203 272 203 272 193 263 180 242 180 175 180 175 169 156 169 156 196 177 196 177 228 107 228 70 228 70 275 107 275 107 248 160 248 160 301 107 301 107 275 70 275 -fill {} -outline {} -tags {floor3 room}]
    set floorLabels($i) 306
    set {floorItems(306)} $i
    $w create text 200.5 284.5 -text 306 -fill $color -anchor c -tags {floor3 label}
    $w create line 341 275 341 283 -fill $color -tags {floor3 wall}
    $w create line 162 197 155 197 -fill $color -tags {floor3 wall}
    $w create line 396 247 399 247 -fill $color -tags {floor3 wall}
    $w create line 399 129 399 311 -fill $color -tags {floor3 wall}
    $w create line 258 202 243 202 -fill $color -tags {floor3 wall}
    $w create line 350 283 350 329 -fill $color -tags {floor3 wall}
    $w create line 251 231 243 231 -fill $color -tags {floor3 wall}
    $w create line 243 220 251 220 -fill $color -tags {floor3 wall}
    $w create line 243 250 243 202 -fill $color -tags {floor3 wall}
    $w create line 155 197 155 190 -fill $color -tags {floor3 wall}
    $w create line 110 192 110 169 -fill $color -tags {floor3 wall}
    $w create line 155 192 110 192 -fill $color -tags {floor3 wall}
    $w create line 155 177 155 169 -fill $color -tags {floor3 wall}
    $w create line 176 197 176 227 -fill $color -tags {floor3 wall}
    $w create line 69 280 69 274 -fill $color -tags {floor3 wall}
    $w create line 21 276 69 276 -fill $color -tags {floor3 wall}
    $w create line 69 262 69 226 -fill $color -tags {floor3 wall}
    $w create line 21 228 69 228 -fill $color -tags {floor3 wall}
    $w create line 21 179 75 179 -fill $color -tags {floor3 wall}
    $w create line 69 179 69 214 -fill $color -tags {floor3 wall}
    $w create line 90 220 90 227 -fill $color -tags {floor3 wall}
    $w create line 90 204 90 202 -fill $color -tags {floor3 wall}
    $w create line 90 203 100 203 -fill $color -tags {floor3 wall}
    $w create line 90 187 90 179 -fill $color -tags {floor3 wall}
    $w create line 90 227 176 227 -fill $color -tags {floor3 wall}
    $w create line 100 179 100 227 -fill $color -tags {floor3 wall}
    $w create line 100 179 87 179 -fill $color -tags {floor3 wall}
    $w create line 96 179 96 129 -fill $color -tags {floor3 wall}
    $w create line 162 169 96 169 -fill $color -tags {floor3 wall}
    $w create line 173 169 176 169 -fill $color -tags {floor3 wall}
    $w create line 182 179 176 179 -fill $color -tags {floor3 wall}
    $w create line 176 129 176 179 -fill $color -tags {floor3 wall}
    $w create line 195 179 226 179 -fill $color -tags {floor3 wall}
    $w create line 224 133 224 179 -fill $color -tags {floor3 wall}
    $w create line 264 179 264 133 -fill $color -tags {floor3 wall}
    $w create line 238 179 264 179 -fill $color -tags {floor3 wall}
    $w create line 273 207 273 193 -fill $color -tags {floor3 wall}
    $w create line 273 235 273 250 -fill $color -tags {floor3 wall}
    $w create line 273 224 273 219 -fill $color -tags {floor3 wall}
    $w create line 273 193 307 193 -fill $color -tags {floor3 wall}
    $w create line 273 222 307 222 -fill $color -tags {floor3 wall}
    $w create line 273 250 307 250 -fill $color -tags {floor3 wall}
    $w create line 384 247 376 247 -fill $color -tags {floor3 wall}
    $w create line 340 206 307 206 -fill $color -tags {floor3 wall}
    $w create line 340 187 340 170 -fill $color -tags {floor3 wall}
    $w create line 340 210 340 201 -fill $color -tags {floor3 wall}
    $w create line 340 247 340 224 -fill $color -tags {floor3 wall}
    $w create line 340 241 307 241 -fill $color -tags {floor3 wall}
    $w create line 376 247 376 170 -fill $color -tags {floor3 wall}
    $w create line 307 250 307 170 -fill $color -tags {floor3 wall}
    $w create line 376 170 307 170 -fill $color -tags {floor3 wall}
    $w create line 315 129 315 170 -fill $color -tags {floor3 wall}
    $w create line 376 283 366 283 -fill $color -tags {floor3 wall}
    $w create line 376 283 376 275 -fill $color -tags {floor3 wall}
    $w create line 399 275 376 275 -fill $color -tags {floor3 wall}
    $w create line 341 275 320 275 -fill $color -tags {floor3 wall}
    $w create line 341 283 350 283 -fill $color -tags {floor3 wall}
    $w create line 298 275 298 329 -fill $color -tags {floor3 wall}
    $w create line 308 275 298 275 -fill $color -tags {floor3 wall}
    $w create line 243 322 243 275 -fill $color -tags {floor3 wall}
    $w create line 243 275 284 275 -fill $color -tags {floor3 wall}
    $w create line 258 322 226 322 -fill $color -tags {floor3 wall}
    $w create line 212 370 212 322 -fill $color -tags {floor3 wall}
    $w create line 214 322 177 322 -fill $color -tags {floor3 wall}
    $w create line 163 370 163 322 -fill $color -tags {floor3 wall}
    $w create line 165 322 129 322 -fill $color -tags {floor3 wall}
    $w create line 84 322 117 322 -fill $color -tags {floor3 wall}
    $w create line 71 322 64 322 -fill $color -tags {floor3 wall}
    $w create line 115 322 115 370 -fill $color -tags {floor3 wall}
    $w create line 66 322 66 370 -fill $color -tags {floor3 wall}
    $w create line 52 322 21 322 -fill $color -tags {floor3 wall}
    $w create line 21 331 0 331 -fill $color -tags {floor3 wall}
    $w create line 21 331 21 133 -fill $color -tags {floor3 wall}
    $w create line 96 133 21 133 -fill $color -tags {floor3 wall}
    $w create line 176 129 96 129 -fill $color -tags {floor3 wall}
    $w create line 315 133 176 133 -fill $color -tags {floor3 wall}
    $w create line 315 129 399 129 -fill $color -tags {floor3 wall}
    $w create line 399 311 350 311 -fill $color -tags {floor3 wall}
    $w create line 350 329 258 329 -fill $color -tags {floor3 wall}
    $w create line 258 322 258 370 -fill $color -tags {floor3 wall}
    $w create line 60 370 258 370 -fill $color -tags {floor3 wall}
    $w create line 60 370 60 391 -fill $color -tags {floor3 wall}
    $w create line 0 391 0 331 -fill $color -tags {floor3 wall}
    $w create line 60 391 0 391 -fill $color -tags {floor3 wall}
    $w create line 307 250 307 242 -fill $color -tags {floor3 wall}
    $w create line 273 250 307 250 -fill $color -tags {floor3 wall}
    $w create line 258 250 243 250 -fill $color -tags {floor3 wall}
}

# Below is the "main program" that creates the floorplan demonstration.

set w .floor
global c currentRoom colors activeFloor
catch {destroy $w}
toplevel $w
wm title $w "Floorplan Canvas Demonstration"
wm iconname $w "Floorplan"
wm geometry $w +20+20
wm minsize $w 100 100

label $w.msg -font $font -wraplength 8i -justify left  -text "This window contains a canvas widget showing the floorplan of Digital Equipment Corporation's Western Research Laboratory.  It has three levels.  At any given time one of the levels is active, meaning that you can see its room structure.  To activate a level, click the left mouse button anywhere on it.  As the mouse moves over the active level, the room under the mouse lights up and its room number appears in the \"Room:\" entry.  You can also type a room number in the entry and the room will light up."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

set f [frame $w.frame]
pack $f -side top -fill both -expand yes
set h [ttk::scrollbar $f.hscroll -orient horizontal]
set v [ttk::scrollbar $f.vscroll -orient vertical]
set f1 [frame $f.f1 -borderwidth 2 -relief sunken]
set c [canvas $f1.c -width 900 -height 500 -highlightthickness 0 \
	   -xscrollcommand [list $h set] \
	   -yscrollcommand [list $v set]]
pack $c -expand yes -fill both
grid $f1 -padx 1 -pady 1 -row 0 -column 0 -rowspan 1 -columnspan 1 -sticky news
grid $v -padx 1 -pady 1 -row 0 -column 1 -rowspan 1 -columnspan 1 -sticky news
grid $h -padx 1 -pady 1 -row 1 -column 0 -rowspan 1 -columnspan 1 -sticky news
grid rowconfig    $f 0 -weight 1 -minsize 0
grid columnconfig $f 0 -weight 1 -minsize 0
pack $f -expand yes -fill both -padx 1 -pady 1

$v configure -command [list $c yview]
$h configure -command [list $c xview]

# Create an entry for displaying and typing in current room.

entry $c.entry -width 10 -textvariable currentRoom

# Choose colors, then fill in the floorplan.

if {[winfo depth $c] > 1} {
    set colors(bg1) #a9c1da
    set colors(outline1) #77889a
    set colors(bg2) #9ab0c6
    set colors(outline2) #687786
    set colors(bg3) #8ba0b3
    set colors(outline3) #596673
    set colors(offices) Black
    set colors(active) #c4d1df
} else {
    set colors(bg1) white
    set colors(outline1) black
    set colors(bg2) white
    set colors(outline2) black
    set colors(bg3) white
    set colors(outline3) black
    set colors(offices) Black
    set colors(active) black
}
set activeFloor ""
floorDisplay $c 3

# Set up event bindings for canvas:

$c bind floor1 <Button-1> "floorDisplay $c 1"
$c bind floor2 <Button-1> "floorDisplay $c 2"
$c bind floor3 <Button-1> "floorDisplay $c 3"
$c bind room <Enter> "newRoom $c"
$c bind room <Leave> {set currentRoom ""}
if {[tk windowingsystem] eq "aqua" && ![package vsatisfies [package provide Tk] 8.7-]} {
    bind $c <Button-3> "$c scan mark %x %y"
    bind $c <B3-Motion> "$c scan dragto %x %y"
} else {
    bind $c <Button-2> "$c scan mark %x %y"
    bind $c <B2-Motion> "$c scan dragto %x %y"
}
bind $c <Destroy> "unset currentRoom"
set currentRoom ""
trace add variable currentRoom write "roomChanged $c"
