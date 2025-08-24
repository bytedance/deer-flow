# Copyright (C) 2008 Pat Thoyts <patthoyts@users.sourceforge.net>
#
#	Calculate a Knight's tour of a chessboard.
#
#	This uses Warnsdorff's rule to calculate the next square each
#	time. This specifies that the next square should be the one that
#	has the least number of available moves.
#
#	Using this rule it is possible to get to a position where
#	there are no squares available to move into. In this implementation
#	this occurs when the starting square is d6.
#
#	To solve this fault an enhancement to the rule is that if we
#	have a choice of squares with an equal score, we should choose
#	the one nearest the edge of the board.
#
#	If the call to the Edgemost function is commented out you can see
#	this occur.
#
#	You can drag the knight to a specific square to start if you wish.
#	If you let it repeat then it will choose random start positions
#	for each new tour.

package require Tk

# Return a list of accessible squares from a given square
proc ValidMoves {square} {
    set moves {}
    foreach pair {{-1 -2} {-2 -1} {-2 1} {-1 2} {1 2} {2 1} {2 -1} {1 -2}} {
        set col [expr {($square % 8) + [lindex $pair 0]}]
        set row [expr {($square / 8) + [lindex $pair 1]}]
        if {$row >= 0 && $row < 8 && $col >= 0 && $col < 8} {
            lappend moves [expr {$row * 8 + $col}]
        }
    }
    return $moves
}

# Return the number of available moves for this square
proc CheckSquare {square} {
    variable visited
    set moves 0
    foreach test [ValidMoves $square] {
        if {[lsearch -exact -integer $visited $test] < 0} {
            incr moves
        }
    }
    return $moves
}

# Select the next square to move to. Returns -1 if there are no available
# squares remaining that we can move to.
proc Next {square} {
    variable visited
    set minimum 9
    set nextSquare -1
    foreach testSquare [ValidMoves $square] {
        if {[lsearch -exact -integer $visited $testSquare] < 0} {
            set count [CheckSquare $testSquare]
            if {$count < $minimum} {
                set minimum $count
                set nextSquare $testSquare
            } elseif {$count == $minimum} {
                # to remove the enhancement to Warnsdorff's rule
                # remove the next line:
                set nextSquare [Edgemost $nextSquare $testSquare]
            }
        }
    }
    return $nextSquare
}

# Select the square nearest the edge of the board
proc Edgemost {a b} {
    set colA [expr {3-int(abs(3.5-($a%8)))}]
    set colB [expr {3-int(abs(3.5-($b%8)))}]
    set rowA [expr {3-int(abs(3.5-($a/8)))}]
    set rowB [expr {3-int(abs(3.5-($b/8)))}]
    return [expr {($colA * $rowA) < ($colB * $rowB) ? $a : $b}]
}

# Display a square number as a standard chess square notation.
proc N {square} {
    return [format %c%d [expr {97 + $square % 8}] \
                [expr {$square / 8 + 1}]]
}

# Perform a Knight's move and schedule the next move.
proc MovePiece {dlg last square} {
    variable visited
    variable delay
    variable continuous
    $dlg.f.txt insert end "[llength $visited]. [N $last] .. [N $square]\n" {}
    $dlg.f.txt see end
    $dlg.f.c itemconfigure [expr {1+$last}] -state normal -outline black
    $dlg.f.c itemconfigure [expr {1+$square}] -state normal -outline red
    $dlg.f.c moveto knight {*}[lrange [$dlg.f.c coords [expr {1+$square}]] 0 1]
    lappend visited $square
    set next [Next $square]
    if {$next ne -1} {
        variable aid [after $delay [list MovePiece $dlg $square $next]]
    } else {
        $dlg.tf.b1 configure -state normal
        if {[llength $visited] == 64} {
            variable initial
            if {$initial == $square} {
                $dlg.f.txt insert end "Closed tour!"
            } else {
                $dlg.f.txt insert end "Success\n" {}
                if {$continuous} {
                    after [expr {$delay * 2}] [namespace code \
                        [list Tour $dlg [expr {int(rand() * 64)}]]]
                }
            }
        } else {
            $dlg.f.txt insert end "FAILED!\n" {}
        }
    }
}

# Begin a new tour of the board given a random start position
proc Tour {dlg {square {}}} {
    variable visited {}
    $dlg.f.txt delete 1.0 end
    $dlg.tf.b1 configure -state disabled
    for {set n 0} {$n < 64} {incr n} {
        $dlg.f.c itemconfigure $n -state disabled -outline black
    }
    if {$square eq {}} {
        set coords [lrange [$dlg.f.c coords knight] 0 1]
        set square [expr {[$dlg.f.c find closest {*}$coords 0 65]-1}]
    }
    variable initial $square
    after idle [list MovePiece $dlg $initial $initial]
}

proc Stop {} {
    variable aid
    catch {after cancel $aid}
}

proc Exit {dlg} {
    Stop
    destroy $dlg
}

proc SetDelay {new} {
    variable delay [expr {int($new)}]
}

proc DragStart {w x y} {
    $w dtag selected
    $w addtag selected withtag current
    variable dragging [list $x $y]
}
proc DragMotion {w x y} {
    variable dragging
    if {[info exists dragging]} {
        $w move selected [expr {$x - [lindex $dragging 0]}] \
            [expr {$y - [lindex $dragging 1]}]
        variable dragging [list $x $y]
    }
}
proc DragEnd {w x y} {
    set square [$w find closest $x $y 0 65]
    $w moveto selected {*}[lrange [$w coords $square] 0 1]
    $w dtag selected
    variable dragging ; unset dragging
}

proc CreateGUI {} {
    catch {destroy .knightstour}
    set dlg [toplevel .knightstour]
    wm title $dlg "Knights tour"
    wm withdraw $dlg
    set f [ttk::frame $dlg.f]
    set c [canvas $f.c -width 240 -height 240]
    text $f.txt -width 10 -height 1 \
        -yscrollcommand [list $f.vs set] -font {Arial 8}
    ttk::scrollbar $f.vs -command [list $f.txt yview]

    variable delay 600
    variable continuous 0
    ttk::frame $dlg.tf
    ttk::label $dlg.tf.ls -text Speed
    ttk::scale $dlg.tf.sc  -from 8 -to 2000 -command [list SetDelay] \
        -variable [namespace which -variable delay]
    ttk::checkbutton $dlg.tf.cc -text Repeat \
        -variable [namespace which -variable continuous]
    ttk::button $dlg.tf.b1 -text Start -command [list Tour $dlg]
    ttk::button $dlg.tf.b2 -text Exit -command [list Exit $dlg]
    set square 0
    for {set row 7} {$row >= 0} {incr row -1} {
        for {set col 0} {$col < 8} {incr col} {
            if {(($col & 1) ^ ($row & 1))} {
                set fill tan3 ; set dfill tan4
            } else {
                set fill bisque ; set dfill bisque3
            }
            set coords [list [expr {$col * 30 + 4}] [expr {$row * 30 + 4}] \
                            [expr {$col * 30 + 30}] [expr {$row * 30 + 30}]]
            $c create rectangle $coords -fill $fill -disabledfill $dfill \
                -width 2 -state disabled -outline black
        }
    }
    if {[tk windowingsystem] ne "x11"} {
        catch {eval font create KnightFont -size -24}
        $c create text 0 0 -font KnightFont -text "\u265e" \
            -anchor nw -tags knight -fill black -activefill "#600000"
    } else {
        # On X11 we cannot reliably tell if the \u265e glyph is available
        # so just use a polygon
        set pts {
            2 25   24 25  21 19   20 8   14 0   10 0   0 13   0 16
            2 17    4 14   5 15    3 17   5 17   9 14  10 15  5 21
        }
        $c create polygon $pts -tag knight -offset 8 \
            -fill black -activefill "#600000"
    }
    $c moveto knight {*}[lrange [$c coords [expr {1 + int(rand() * 64)}]] 0 1]
    $c bind knight <Button-1> [namespace code [list DragStart %W %x %y]]
    $c bind knight <Motion> [namespace code [list DragMotion %W %x %y]]
    $c bind knight <ButtonRelease-1> [namespace code [list DragEnd %W %x %y]]

    grid $c $f.txt $f.vs  -sticky news
    grid rowconfigure    $f 0 -weight 1
    grid columnconfigure $f 1 -weight 1

    grid $f - - - - - -sticky news
    set things [list $dlg.tf.ls $dlg.tf.sc $dlg.tf.cc $dlg.tf.b1]
    if {![info exists ::widgetDemo]} {
	lappend things $dlg.tf.b2
	if {[tk windowingsystem] ne "aqua"} {
	    set things [linsert $things 0 [ttk::sizegrip $dlg.tf.sg]]
	}
    }
    pack {*}$things -side right
    if {[tk windowingsystem] eq "aqua"} {
	pack configure {*}$things -padx {4 4} -pady {12 12}
	pack configure [lindex $things 0] -padx {4 24}
	pack configure [lindex $things end] -padx {16 4}
    }
    grid $dlg.tf  - - - - - -sticky ew
    if {[info exists ::widgetDemo]} {
        grid [addSeeDismiss $dlg.buttons $dlg] - - - - - -sticky ew
    }

    grid rowconfigure $dlg 0 -weight 1
    grid columnconfigure $dlg 0 -weight 1

    bind $dlg <Control-F2> {console show}
    bind $dlg <Return> [list $dlg.tf.b1 invoke]
    bind $dlg <Escape> [list $dlg.tf.b2 invoke]
    bind $dlg <Destroy> [namespace code [list Stop]]
    wm protocol $dlg WM_DELETE_WINDOW [namespace code [list Exit $dlg]]

    wm deiconify $dlg
    tkwait window $dlg
}

if {![winfo exists .knightstour]} {
    if {![info exists widgetDemo]} { wm withdraw . }
    set r [catch [linsert $argv 0 CreateGUI] err]
    if {$r} {
	tk_messageBox -icon error -title "Error" -message $err
    }
    if {![info exists widgetDemo]} { exit $r }
}
