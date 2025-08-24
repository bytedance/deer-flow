# tdbcmysql.tcl --
#
#	Class definitions and Tcl-level methods for the tdbc::mysql bridge.
#
# Copyright (c) 2008 by Kevin B. Kenny
# See the file "license.terms" for information on usage and redistribution
# of this file, and for a DISCLAIMER OF ALL WARRANTIES.
#
# RCS: @(#) $Id: tdbcmysql.tcl,v 1.47 2008/02/27 02:08:27 kennykb Exp $
#
#------------------------------------------------------------------------------

package require tdbc

::namespace eval ::tdbc::mysql {

    namespace export connection datasources drivers

}

#------------------------------------------------------------------------------
#
# tdbc::mysql::connection --
#
#	Class representing a connection to a database through MYSQL.
#
#-------------------------------------------------------------------------------

::oo::class create ::tdbc::mysql::connection {

    superclass ::tdbc::connection

    # The constructor is written in C. It takes alternating keywords
    # and values pairs as its argumenta.  (See the manual page for the
    # available options.)

    variable foreignKeysStatement

    # The 'statementCreate' method delegates to the constructor of the
    # statement class

    forward statementCreate ::tdbc::mysql::statement create

    # The 'columns' method returns a dictionary describing the tables
    # in the database

    method columns {table {pattern %}} {

	# To return correct lengths of CHARACTER and BINARY columns,
	# we need to know the maximum lengths of characters in each
	# collation. We cache this information only once, on the first
	# call to 'columns'.

	if {[my NeedCollationInfo]} {
	    my SetCollationInfo {*}[my allrows -as lists {
		SELECT coll.id, cs.maxlen
		FROM INFORMATION_SCHEMA.COLLATIONS coll,
		     INFORMATION_SCHEMA.CHARACTER_SETS cs
		WHERE cs.CHARACTER_SET_NAME = coll.CHARACTER_SET_NAME
		ORDER BY coll.id DESC
	    }]
	}

	return [my Columns $table $pattern]
    }

    # The 'preparecall' method gives a portable interface to prepare
    # calls to stored procedures.  It delegates to 'prepare' to do the
    # actual work.

    method preparecall {call} {
	regexp {^[[:space:]]*(?:([A-Za-z_][A-Za-z_0-9]*)[[:space:]]*=)?(.*)} \
	    $call -> varName rest
	if {$varName eq {}} {
	    my prepare "CALL $rest"
	} else {
	    my prepare \\{:$varName=$rest\\}
	}
    }

    # The 'init', 'begintransaction', 'commit, 'rollback', 'tables'
    # 'NeedCollationInfo', 'SetCollationInfo', and 'Columns' methods
    # are implemented in C.

    # The 'BuildForeignKeysStatements' method builds a SQL statement to
    # retrieve the foreign keys from a database. (It executes once the
    # first time the 'foreignKeys' method is executed, and retains the
    # prepared statements for reuse.)  It is slightly nonstandard because
    # MYSQL doesn't name the PRIMARY constraints uniquely.

    method BuildForeignKeysStatement {} {

	foreach {exists1 clause1} {
	    0 {}
	    1 { AND fkc.REFERENCED_TABLE_NAME = :primary}
	} {
	    foreach {exists2 clause2} {
		0 {}
		1 { AND fkc.TABLE_NAME = :foreign}
	    } {
		set stmt [my prepare "
	     SELECT rc.CONSTRAINT_SCHEMA AS \"foreignConstraintSchema\",
		    rc.CONSTRAINT_NAME AS \"foreignConstraintName\",
		    rc.UPDATE_RULE AS \"updateAction\",
		    rc.DELETE_RULE AS \"deleteAction\",
		    fkc.REFERENCED_TABLE_SCHEMA AS \"primarySchema\",
		    fkc.REFERENCED_TABLE_NAME AS \"primaryTable\",
		    fkc.REFERENCED_COLUMN_NAME AS \"primaryColumn\",
		    fkc.TABLE_SCHEMA AS \"foreignSchema\",
		    fkc.TABLE_NAME AS \"foreignTable\",
		    fkc.COLUMN_NAME AS \"foreignColumn\",
		    fkc.ORDINAL_POSITION AS \"ordinalPosition\"
	     FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
	     INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE fkc
		     ON fkc.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
		    AND fkc.CONSTRAINT_SCHEMA = rc.CONSTRAINT_SCHEMA
	     WHERE 1=1
		 $clause1
		 $clause2
"]
		dict set foreignKeysStatement $exists1 $exists2 $stmt
	    }
	}
    }
}

#------------------------------------------------------------------------------
#
# tdbc::mysql::statement --
#
#	The class 'tdbc::mysql::statement' models one statement against a
#       database accessed through an MYSQL connection
#
#------------------------------------------------------------------------------

::oo::class create ::tdbc::mysql::statement {

    superclass ::tdbc::statement

    # The 'resultSetCreate' method forwards to the constructor of the
    # result set.

    forward resultSetCreate ::tdbc::mysql::resultset create

    # Methods implemented in C:
    #
    # constructor connection SQLCode
    #	The constructor accepts the handle to the connection and the SQL code
    #	for the statement to prepare.  It creates a subordinate namespace to
    #	hold the statement's active result sets, and then delegates to the
    #	'init' method, written in C, to do the actual work of preparing the
    #	statement.
    # params
    #   Returns descriptions of the parameters of a statement.
    # paramtype paramname ?direction? type ?precision ?scale??
    #   Declares the type of a parameter in the statement

}

#------------------------------------------------------------------------------
#
# tdbc::mysql::resultset --
#
#	The class 'tdbc::mysql::resultset' models the result set that is
#	produced by executing a statement against an MYSQL database.
#
#------------------------------------------------------------------------------

::oo::class create ::tdbc::mysql::resultset {

    superclass ::tdbc::resultset

    # Methods implemented in C include:

    # constructor statement ?dictionary?
    #     -- Executes the statement against the database, optionally providing
    #        a dictionary of substituted parameters (default is to get params
    #        from variables in the caller's scope).
    # columns
    #     -- Returns a list of the names of the columns in the result.
    # nextdict
    #     -- Stores the next row of the result set in the given variable in
    #        the caller's scope as a dictionary whose keys are
    #        column names and whose values are column values, or else
    #        as a list of cells.
    # nextlist
    #     -- Stores the next row of the result set in the given variable in
    #        the caller's scope as a list of cells.
    # rowcount
    #     -- Returns a count of rows affected by the statement, or -1
    #        if the count of rows has not been determined.

}
