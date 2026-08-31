       PROCESS SQL
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2021                             *
      *                                                                *
      *                    ADD Policy                                  *
      *                                                                *
      *   To add full details of an individual policy:                 *
      *     Endowment, House, Motor, Commercial                        *
      *                                                                *
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LGAPDB01.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
      *
       DATA DIVISION.

       WORKING-STORAGE SECTION.

      *----------------------------------------------------------------*
      * Common defintions                                              *
      *----------------------------------------------------------------*
      * Run time (debug) infomation for this invocation
        01  WS-HEADER.
           03 WS-EYECATCHER            PIC X(16)
                                        VALUE 'LGAPDB01------WS'.
           03 WS-TRANSID               PIC X(4).
           03 WS-TERMID                PIC X(4).
           03 WS-TASKNUM               PIC 9(7).
           03 WS-FILLER                PIC X.
           03 WS-ADDR-DFHCOMMAREA      USAGE is POINTER.
           03 WS-CALEN                 PIC S9(4) COMP.

      * Variables for time/date processing
       01  ABS-TIME                    PIC S9(8) COMP VALUE +0.
       01  TIME1                       PIC X(8)  VALUE SPACES.
       01  DATE1                       PIC X(10) VALUE SPACES.

      * Error Message structure
       01  ERROR-MSG.
           03 EM-DATE                  PIC X(8)  VALUE SPACES.
           03 FILLER                   PIC X     VALUE SPACES.
           03 EM-TIME                  PIC X(6)  VALUE SPACES.
           03 FILLER                   PIC X(9)  VALUE ' LGAPDB01'.
           03 EM-VARIABLE.
             05 FILLER                 PIC X(6)  VALUE ' CNUM='.
             05 EM-CUSNUM              PIC X(10)  VALUE SPACES.
             05 FILLER                 PIC X(6)  VALUE ' PNUM='.
             05 EM-POLNUM              PIC X(10)  VALUE SPACES.
             05 EM-SQLREQ              PIC X(16) VALUE SPACES.
             05 FILLER                 PIC X(9)  VALUE ' SQLCODE='.
             05 EM-SQLRC               PIC +9(5) USAGE DISPLAY.

       01  CA-ERROR-MSG.
           03 FILLER                   PIC X(9)  VALUE 'COMMAREA='.
           03 CA-DATA                  PIC X(90) VALUE SPACES.
      *----------------------------------------------------------------*

      *----------------------------------------------------------------*
      * Definitions required for data manipulation                     *
      *----------------------------------------------------------------*
      * Fields to be used to check that commarea is correct length
       01  WS-COMMAREA-LENGTHS.
           03 WS-CA-HEADER-LEN         PIC S9(4) COMP VALUE +28.
           03 WS-REQUIRED-CA-LEN       PIC S9(4)      VALUE +0.

      * Define a varying length character string to contain actual
      * amount of data that will be inserted to Varchar field
       01 WS-VARY-FIELD.
          49 WS-VARY-LEN               PIC S9(4) COMP.
          49 WS-VARY-CHAR              PIC X(3900).

      *    Include copybook for defintion of customer details length
      * >>> BEGIN EXEC_SQL_INCLUDE LGPOLICY (LGPOLICY.cpy)
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2020                             *
      *                                                                *
      ******************************************************************
      *               COPYBOOK for Policy details                      *
      *                                                                *
      *   Structures to map values obtained from DB2 tables:           *
      *   Customer, Policy, Endowment, House and Motor.                *
      *                                                                *
      *   All lengths of policy fields will be defined here so that    *
      *   if any of the DB2 table contents change the lengths will     *
      *   only need to be changed here.                                *
      *                                                                *
      ******************************************************************
       01  WS-POLICY-LENGTHS.
           03 WS-CUSTOMER-LEN          PIC S9(4) COMP VALUE +72.
           03 WS-POLICY-LEN            PIC S9(4) COMP VALUE +72.
           03 WS-ENDOW-LEN             PIC S9(4) COMP VALUE +52.
           03 WS-HOUSE-LEN             PIC S9(4) COMP VALUE +58.
           03 WS-MOTOR-LEN             PIC S9(4) COMP VALUE +65.
           03 WS-COMM-LEN              PIC S9(4) COMP VALUE +1102.
           03 WS-CLAIM-LEN             PIC S9(4) COMP VALUE +546.
           03 WS-FULL-ENDOW-LEN        PIC S9(4) COMP VALUE +124.
           03 WS-FULL-HOUSE-LEN        PIC S9(4) COMP VALUE +130.
           03 WS-FULL-MOTOR-LEN        PIC S9(4) COMP VALUE +137.
           03 WS-FULL-COMM-LEN         PIC S9(4) COMP VALUE +1174.
           03 WS-FULL-CLAIM-LEN        PIC S9(4) COMP VALUE +618.
           03 WS-SUMRY-ENDOW-LEN       PIC S9(4) COMP VALUE +25.

       01  DB2-CUSTOMER.
           03 DB2-FIRSTNAME            PIC X(10).
           03 DB2-LASTNAME             PIC X(20).
           03 DB2-DATEOFBIRTH          PIC X(10).
           03 DB2-HOUSENAME            PIC X(20).
           03 DB2-HOUSENUMBER          PIC X(4).
           03 DB2-POSTCODE             PIC X(8).
           03 DB2-PHONE-MOBILE         PIC X(20).
           03 DB2-PHONE-HOME           PIC X(20).
           03 DB2-EMAIL-ADDRESS        PIC X(100).

       01  DB2-POLICY.
           03 DB2-POLICYTYPE           PIC X.
           03 DB2-POLICYNUMBER         PIC 9(10).
           03 DB2-POLICY-COMMON.
              05 DB2-ISSUEDATE         PIC X(10).
              05 DB2-EXPIRYDATE        PIC X(10).
              05 DB2-LASTCHANGED       PIC X(26).
              05 DB2-BROKERID          PIC 9(10).
              05 DB2-BROKERSREF        PIC X(10).
              05 DB2-PAYMENT           PIC 9(6).

       01  DB2-ENDOWMENT.
           03 DB2-ENDOW-FIXED.
              05 DB2-E-WITHPROFITS      PIC X.
              05 DB2-E-EQUITIES         PIC X.
              05 DB2-E-MANAGEDFUND      PIC X.
              05 DB2-E-FUNDNAME         PIC X(10).
              05 DB2-E-TERM             PIC 9(2).
              05 DB2-E-SUMASSURED       PIC 9(6).
              05 DB2-E-LIFEASSURED      PIC X(31).
           03 DB2-E-PADDINGDATA         PIC X(32611).

       01  DB2-HOUSE.
           03 DB2-H-PROPERTYTYPE       PIC X(15).
           03 DB2-H-BEDROOMS           PIC 9(3).
           03 DB2-H-VALUE              PIC 9(8).
           03 DB2-H-HOUSENAME          PIC X(20).
           03 DB2-H-HOUSENUMBER        PIC X(4).
           03 DB2-H-POSTCODE           PIC X(8).

       01  DB2-MOTOR.
           03 DB2-M-MAKE               PIC X(15).
           03 DB2-M-MODEL              PIC X(15).
           03 DB2-M-VALUE              PIC 9(6).
           03 DB2-M-REGNUMBER          PIC X(7).
           03 DB2-M-COLOUR             PIC X(8).
           03 DB2-M-CC                 PIC 9(4).
           03 DB2-M-MANUFACTURED       PIC X(10).
           03 DB2-M-PREMIUM            PIC 9(6).
           03 DB2-M-ACCIDENTS          PIC 9(6).

       01  DB2-COMMERCIAL.
           03 DB2-B-Address            PIC X(255).
           03 DB2-B-Postcode           PIC X(8).
           03 DB2-B-Latitude           PIC X(11).
           03 DB2-B-Longitude          PIC X(11).
           03 DB2-B-Customer           PIC X(255).
           03 DB2-B-PropType           PIC X(255).
           03 DB2-B-FirePeril          PIC 9(4).
           03 DB2-B-FirePremium        PIC 9(8).
           03 DB2-B-CrimePeril         PIC 9(4).
           03 DB2-B-CrimePremium       PIC 9(8).
           03 DB2-B-FloodPeril         PIC 9(4).
           03 DB2-B-FloodPremium       PIC 9(8).
           03 DB2-B-WeatherPeril       PIC 9(4).
           03 DB2-B-WeatherPremium     PIC 9(8).
           03 DB2-B-Status             PIC 9(4).
           03 DB2-B-RejectReason       PIC X(255).

       01  DB2-CLAIM.
           03 DB2-C-Num                PIC 9(10).
           03 DB2-C-Date               PIC X(10).
           03 DB2-C-Paid               PIC 9(8).
           03 DB2-C-Value              PIC 9(8).
           03 DB2-C-Cause              PIC X(255).
           03 DB2-C-Observations       PIC X(255).
      * <<< END EXEC_SQL_INCLUDE LGPOLICY
      *----------------------------------------------------------------*

      *----------------------------------------------------------------*
      * Definitions required by SQL statement                          *
      *   DB2 datatypes to COBOL equivalents                           *
      *     SMALLINT    :   PIC S9(4) COMP                             *
      *     INTEGER     :   PIC S9(9) COMP                             *
      *     DATE        :   PIC X(10)                                  *
      *     TIMESTAMP   :   PIC X(26)                                  *
      *----------------------------------------------------------------*
      * Host variables for input to DB2 integer types
       01 DB2-IN-INTEGERS.
           03 DB2-CUSTOMERNUM-INT      PIC S9(9) COMP.
           03 DB2-BROKERID-INT         PIC S9(9) COMP.
           03 DB2-PAYMENT-INT          PIC S9(9) COMP.
           03 DB2-E-TERM-SINT          PIC S9(4) COMP.
           03 DB2-E-SUMASSURED-INT     PIC S9(9) COMP.
           03 DB2-E-PADDING-LEN        PIC S9(9) COMP.
           03 DB2-H-BEDROOMS-SINT      PIC S9(4) COMP.
           03 DB2-H-VALUE-INT          PIC S9(9) COMP.
           03 DB2-M-VALUE-INT          PIC S9(9) COMP.
           03 DB2-M-CC-SINT            PIC S9(4) COMP.
           03 DB2-M-PREMIUM-int        PIC S9(9) COMP.
           03 DB2-M-ACCIDENTS-int      PIC S9(9) COMP.
           03 DB2-B-FirePeril-Int      PIC S9(4) COMP.
           03 DB2-B-FirePremium-Int    PIC S9(9) COMP.
           03 DB2-B-CrimePeril-Int     PIC S9(4) COMP.
           03 DB2-B-CrimePremium-Int   PIC S9(9) COMP.
           03 DB2-B-FloodPeril-Int     PIC S9(4) COMP.
           03 DB2-B-FloodPremium-Int   PIC S9(9) COMP.
           03 DB2-B-WeatherPeril-Int   PIC S9(4) COMP.
           03 DB2-B-WeatherPremium-Int PIC S9(9) COMP.
           03 DB2-B-Status-Int         PIC S9(4) COMP.
           03 DB2-C-Policynum-Int      PIC S9(9) COMP.
           03 DB2-C-Num-INT            PIC S9(9) COMP Value +0.
           03 DB2-C-Paid-INT           PIC S9(9) COMP.
           03 DB2-C-Value-INT          PIC S9(9) COMP.

       01 DB2-OUT-INTEGERS.
           03 DB2-POLICYNUM-INT        PIC S9(9) COMP VALUE +0.
      *----------------------------------------------------------------*
       01  LGAPVS01                    PIC X(8)  VALUE 'LGAPVS01'.
      *----------------------------------------------------------------*
      *    DB2 CONTROL
      *----------------------------------------------------------------*
      * SQLCA DB2 communications area
      * >>> BEGIN EXEC_SQL_INCLUDE SQLCA (<builtin:SQLCA>)
      *****************************************************************
      * SQLCA - DB2 SQL communication area (standard layout).         *
      * Supplied by cobol_transformer: DB2 provides this at precompile*
      * time on z/OS, so no copybook file exists in the source tree.  *
      *****************************************************************
       01  SQLCA.
           05  SQLCAID            PIC X(8).
           05  SQLCABC            PIC S9(9) COMP-5.
           05  SQLCODE            PIC S9(9) COMP-5.
           05  SQLERRM.
               49  SQLERRML       PIC S9(4) COMP-5.
               49  SQLERRMC       PIC X(70).
           05  SQLERRP            PIC X(8).
           05  SQLERRD            OCCURS 6 TIMES
                                  PIC S9(9) COMP-5.
           05  SQLWARN.
               10  SQLWARN0       PIC X.
               10  SQLWARN1       PIC X.
               10  SQLWARN2       PIC X.
               10  SQLWARN3       PIC X.
               10  SQLWARN4       PIC X.
               10  SQLWARN5       PIC X.
               10  SQLWARN6       PIC X.
               10  SQLWARN7       PIC X.
               10  SQLWARN8       PIC X.
               10  SQLWARN9       PIC X.
               10  SQLWARNA       PIC X.
           05  SQLSTATE           PIC X(5).
      * <<< END EXEC_SQL_INCLUDE SQLCA


      ******************************************************************
      *    L I N K A G E     S E C T I O N
      ******************************************************************
      * >>> LINKAGE SECTION promoted to WORKING-STORAGE by cobol_transformer:
      * >>> no CICS caller supplies a commarea, so these items need storage.
      *LINKAGE SECTION.

       01  DFHCOMMAREA.
      * >>> BEGIN EXEC_SQL_INCLUDE LGCMAREA (LGCMAREA.cpy)
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2020                             *
      *                                                                *
      *               COPYBOOK for COMMAREA structure                  *
      *                                                                *
      *   This commarea can be used for all functions                  *
      *                                                                *
      ******************************************************************
           03 CA-REQUEST-ID            PIC X(6).
           03 CA-RETURN-CODE           PIC 9(2).
           03 CA-CUSTOMER-NUM          PIC 9(10).
           03 CA-REQUEST-SPECIFIC      PIC X(32482).
      *    Fields used in INQ All and ADD customer
           03 CA-CUSTOMER-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-FIRST-NAME         PIC X(10).
              05 CA-LAST-NAME          PIC X(20).
              05 CA-DOB                PIC X(10).
              05 CA-HOUSE-NAME         PIC X(20).
              05 CA-HOUSE-NUM          PIC X(4).
              05 CA-POSTCODE           PIC X(8).
              05 CA-NUM-POLICIES       PIC 9(3).
              05 CA-PHONE-MOBILE       PIC X(20).
              05 CA-PHONE-HOME         PIC X(20).
              05 CA-EMAIL-ADDRESS      PIC X(100).
              05 CA-POLICY-DATA        PIC X(32267).
      *    Fields used in Customer security call
           03 CA-CUSTSECR-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-CUSTSECR-PASS      PIC X(32).
              05 CA-CUSTSECR-COUNT     PIC X(4).
              05 CA-CUSTSECR-STATE     PIC X.
              05 CA-CUSTSECR-DATA      PIC X(32445).
      *    Fields used in INQ, UPD, ADD & DELETE policy
           03 CA-POLICY-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-POLICY-NUM         PIC 9(10).
      *       Common policy details
              05 CA-POLICY-COMMON.
                 07 CA-ISSUE-DATE      PIC X(10).
                 07 CA-EXPIRY-DATE     PIC X(10).
                 07 CA-LASTCHANGED     PIC X(26).
                 07 CA-BROKERID        PIC 9(10).
                 07 CA-BROKERSREF      PIC X(10).
                 07 CA-PAYMENT         PIC 9(6).
              05 CA-POLICY-SPECIFIC    PIC X(32400).
      *       Endowment policy description
              05 CA-ENDOWMENT REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-E-WITH-PROFITS    PIC X.
                 07 CA-E-EQUITIES        PIC X.
                 07 CA-E-MANAGED-FUND    PIC X.
                 07 CA-E-FUND-NAME       PIC X(10).
                 07 CA-E-TERM            PIC 99.
                 07 CA-E-SUM-ASSURED     PIC 9(6).
                 07 CA-E-LIFE-ASSURED    PIC X(31).
                 07 CA-E-PADDING-DATA    PIC X(32348).
      *       House policy description
              05 CA-HOUSE REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-H-PROPERTY-TYPE   PIC X(15).
                 07 CA-H-BEDROOMS        PIC 9(3).
                 07 CA-H-VALUE           PIC 9(8).
                 07 CA-H-HOUSE-NAME      PIC X(20).
                 07 CA-H-HOUSE-NUMBER    PIC X(4).
                 07 CA-H-POSTCODE        PIC X(8).
                 07 CA-H-FILLER          PIC X(32342).
      *       Motor policy description
              05 CA-MOTOR REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-M-MAKE            PIC X(15).
                 07 CA-M-MODEL           PIC X(15).
                 07 CA-M-VALUE           PIC 9(6).
                 07 CA-M-REGNUMBER       PIC X(7).
                 07 CA-M-COLOUR          PIC X(8).
                 07 CA-M-CC              PIC 9(4).
                 07 CA-M-MANUFACTURED    PIC X(10).
                 07 CA-M-PREMIUM         PIC 9(6).
                 07 CA-M-ACCIDENTS       PIC 9(6).
                 07 CA-M-FILLER          PIC X(32323).
      *       Commercial policy description
              05 CA-COMMERCIAL REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-B-Address         PIC X(255).
                 07 CA-B-Postcode        PIC X(8).
                 07 CA-B-Latitude        PIC X(11).
                 07 CA-B-Longitude       PIC X(11).
                 07 CA-B-Customer        PIC X(255).
                 07 CA-B-PropType        PIC X(255).
                 07 CA-B-FirePeril       PIC 9(4).
                 07 CA-B-FirePremium     PIC 9(8).
                 07 CA-B-CrimePeril      PIC 9(4).
                 07 CA-B-CrimePremium    PIC 9(8).
                 07 CA-B-FloodPeril      PIC 9(4).
                 07 CA-B-FloodPremium    PIC 9(8).
                 07 CA-B-WeatherPeril    PIC 9(4).
                 07 CA-B-WeatherPremium  PIC 9(8).
                 07 CA-B-Status          PIC 9(4).
                 07 CA-B-RejectReason    PIC X(255).
                 07 CA-B-FILLER          PIC X(31298).
      *       CLAIM policy description
              05 CA-CLAIM      REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-C-Num             PIC 9(10).
                 07 CA-C-Date            PIC X(10).
                 07 CA-C-Paid            PIC 9(8).
                 07 CA-C-Value           PIC 9(8).
                 07 CA-C-Cause           PIC X(255).
                 07 CA-C-Observations    PIC X(255).
                 07 CA-C-FILLER          PIC X(31854).
      * <<< END EXEC_SQL_INCLUDE LGCMAREA


      ******************************************************************
      *    P R O C E D U R E S
      ******************************************************************
      * >>> TOOL-GENERATED MOCK SUPPORT FIELDS <<<
       01  EIBTRNID     PIC X(4) VALUE 'GENA'.
       01  EIBTASKN     PIC S9(7) COMP-3 VALUE 1.
       01  EIBTRMID     PIC X(4) VALUE 'TRM1'.
       01  EIBCALEN     PIC S9(4) COMP VALUE 9999.
       PROCEDURE DIVISION.

      *----------------------------------------------------------------*
       MAINLINE SECTION.

      * initialize working storage variables
           INITIALIZE WS-HEADER.
      * set up general variable
           MOVE EIBTRNID TO WS-TRANSID.
           MOVE EIBTRMID TO WS-TERMID.
           MOVE EIBTASKN TO WS-TASKNUM.
           MOVE EIBCALEN TO WS-CALEN.
      *----------------------------------------------------------------*

      * initialize DB2 host variables
           INITIALIZE DB2-IN-INTEGERS.
           INITIALIZE DB2-OUT-INTEGERS.

      *----------------------------------------------------------------*
      * Check commarea and obtain required details                     *
      *----------------------------------------------------------------*
      * If NO commarea received issue an ABEND
           IF EIBCALEN IS EQUAL TO ZERO
               MOVE ' NO COMMAREA RECEIVED' TO EM-VARIABLE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS ABEND ABCODE('LGCA') NODUMP END-EXEC
               DISPLAY '>>> MOCK ABEND @MAINLINE: ' 'ABCODE=LGCA'
               GOBACK
           END-IF

      * initialize commarea return code to zero
           MOVE '00' TO CA-RETURN-CODE
           SET WS-ADDR-DFHCOMMAREA TO ADDRESS OF DFHCOMMAREA.

      * Convert commarea customer & policy nums to DB2 integer format
           MOVE CA-CUSTOMER-NUM TO DB2-CUSTOMERNUM-INT
           MOVE ZERO            TO DB2-C-PolicyNum-INT
      * and save in error msg field incase required
           MOVE CA-CUSTOMER-NUM TO EM-CUSNUM

      * Check commarea length
           ADD WS-CA-HEADER-LEN TO WS-REQUIRED-CA-LEN

           EVALUATE CA-REQUEST-ID

             WHEN '01AEND'
               ADD WS-FULL-ENDOW-LEN TO WS-REQUIRED-CA-LEN
               MOVE 'E' TO DB2-POLICYTYPE

             WHEN '01AHOU'
               ADD WS-FULL-HOUSE-LEN TO WS-REQUIRED-CA-LEN
               MOVE 'H' TO DB2-POLICYTYPE

             WHEN '01AMOT'
               ADD WS-FULL-MOTOR-LEN TO WS-REQUIRED-CA-LEN
               MOVE 'M' TO DB2-POLICYTYPE

             WHEN '01ACOM'
               ADD WS-FULL-COMM-LEN TO WS-REQUIRED-CA-LEN
               MOVE 'C' TO DB2-POLICYTYPE

             WHEN OTHER
      *        Request is not recognised or supported
               MOVE '99' TO CA-RETURN-CODE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @MAINLINE'
               GOBACK

           END-EVALUATE

      *    if less set error return code and return to caller
           IF EIBCALEN IS LESS THAN WS-REQUIRED-CA-LEN
             MOVE '98' TO CA-RETURN-CODE
      *      EXEC CICS RETURN END-EXEC
             DISPLAY '>>> MOCK RETURN @MAINLINE'
             GOBACK
           END-IF

      *----------------------------------------------------------------*
      *    Perform the INSERTs against appropriate tables              *
      *----------------------------------------------------------------*
      *    Call procedure to Insert row in policy table
           PERFORM INSERT-POLICY

      *    Call appropriate routine to insert row to specific
      *    policy type table.
           EVALUATE CA-REQUEST-ID

             WHEN '01AEND'
               PERFORM INSERT-ENDOW

             WHEN '01AHOU'
               PERFORM INSERT-HOUSE

             WHEN '01AMOT'
               PERFORM INSERT-MOTOR

             WHEN '01ACOM'
               PERFORM INSERT-COMMERCIAL

             WHEN OTHER
      *        Request is not recognised or supported
               MOVE '99' TO CA-RETURN-CODE

           END-EVALUATE

      *      EXEC CICS Link Program(LGAPVS01)
      *           Commarea(DFHCOMMAREA)
      *         LENGTH(32500)
      *      END-EXEC.
             DISPLAY '>>> MOCK LINK @MAINLINE: ' 'LGAPVS01'.


      * Return to caller
      *    EXEC CICS RETURN END-EXEC.
           DISPLAY '>>> MOCK RETURN @MAINLINE'
           GOBACK.

       MAINLINE-EXIT.
           EXIT.
      *----------------------------------------------------------------*


      *================================================================*
      *  Issue INSERT on Policy table using values passed in commarea  *
      * set the timestamp and allow DB2 to allocate a policy number.   *
      *================================================================*
       INSERT-POLICY.

      *    Move numeric fields to integer format
           MOVE CA-BROKERID TO DB2-BROKERID-INT
           MOVE CA-PAYMENT TO DB2-PAYMENT-INT

           MOVE ' INSERT POLICY' TO EM-SQLREQ
      *    EXEC SQL
      *      INSERT INTO POLICY
      *                ( POLICYNUMBER,
      *                  CUSTOMERNUMBER,
      *                  ISSUEDATE,
      *                  EXPIRYDATE,
      *                  POLICYTYPE,
      *                  LASTCHANGED,
      *                  BROKERID,
      *                  BROKERSREFERENCE,
      *                  PAYMENT           )
      *         VALUES ( DEFAULT,
      *                  :DB2-CUSTOMERNUM-INT,
      *                  :CA-ISSUE-DATE,
      *                  :CA-EXPIRY-DATE,
      *                  :DB2-POLICYTYPE,
      *                  CURRENT TIMESTAMP,
      *                  :DB2-BROKERID-INT,
      *                  :CA-BROKERSREF,
      *                  :DB2-PAYMENT-INT      )
      *    END-EXEC
           DISPLAY '>>> MOCK INSERT @INSERT-POLICY: ' 'TABLE=POLICY'
           MOVE 0 TO SQLCODE

           Evaluate SQLCODE

             When 0
               MOVE '00' TO CA-RETURN-CODE

             When -530
               MOVE '70' TO CA-RETURN-CODE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @INSERT-POLICY'
               GOBACK

             When Other
               MOVE '90' TO CA-RETURN-CODE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @INSERT-POLICY'
               GOBACK

           END-Evaluate.

      *    get value of assigned policy number
      *    EXEC SQL
      *      SET :DB2-POLICYNUM-INT = IDENTITY_VAL_LOCAL()
      *    END-EXEC
           DISPLAY '>>> MOCK SET @INSERT-POLICY'
           MOVE 1 TO DB2-POLICYNUM-INT
           MOVE 0 TO SQLCODE
           MOVE DB2-POLICYNUM-INT TO CA-POLICY-NUM
      *    and save in error msg field incase required
           MOVE CA-POLICY-NUM TO EM-POLNUM

      *    get value of assigned Timestamp
      *    EXEC SQL
      *      SELECT LASTCHANGED
      *        INTO :CA-LASTCHANGED
      *        FROM POLICY
      *        WHERE POLICYNUMBER = :DB2-POLICYNUM-INT
      *    END-EXEC.
           DISPLAY '>>> MOCK SELECT @INSERT-POLICY: ' 'TABLE=POLICY'
           MOVE 'DUMMY' TO CA-LASTCHANGED
           MOVE 0 TO SQLCODE.
           EXIT.

      *================================================================*
      * Issue INSERT on endowment table using values passed in commarea*
      *================================================================*
       INSERT-ENDOW.

      *    Move numeric fields to integer format
           MOVE CA-E-TERM        TO DB2-E-TERM-SINT
           MOVE CA-E-SUM-ASSURED TO DB2-E-SUMASSURED-INT

           MOVE ' INSERT ENDOW ' TO EM-SQLREQ
      *----------------------------------------------------------------*
      *    There are 2 versions of INSERT...                           *
      *      one which updates all fields including Varchar            *
      *      one which updates all fields Except Varchar               *
      *----------------------------------------------------------------*
           SUBTRACT WS-REQUIRED-CA-LEN FROM EIBCALEN
               GIVING WS-VARY-LEN

           IF WS-VARY-LEN IS GREATER THAN ZERO
      *       Commarea contains data for Varchar field
              MOVE CA-E-PADDING-DATA
                  TO WS-VARY-CHAR(1:WS-VARY-LEN)
      *       EXEC SQL
      *         INSERT INTO ENDOWMENT
      *                   ( POLICYNUMBER,
      *                     WITHPROFITS,
      *                     EQUITIES,
      *                     MANAGEDFUND,
      *                     FUNDNAME,
      *                     TERM,
      *                     SUMASSURED,
      *                     LIFEASSURED,
      *                     PADDINGDATA    )
      *            VALUES ( :DB2-POLICYNUM-INT,
      *                     :CA-E-WITH-PROFITS,
      *                     :CA-E-EQUITIES,
      *                     :CA-E-MANAGED-FUND,
      *                     :CA-E-FUND-NAME,
      *                     :DB2-E-TERM-SINT,
      *                     :DB2-E-SUMASSURED-INT,
      *                     :CA-E-LIFE-ASSURED,
      *                     :WS-VARY-FIELD )
      *       END-EXEC
              DISPLAY '>>> MOCK INSERT @INSERT-ENDOW: '
                  'TABLE=ENDOWMENT'
              MOVE 0 TO SQLCODE
           ELSE
      *       EXEC SQL
      *         INSERT INTO ENDOWMENT
      *                   ( POLICYNUMBER,
      *                     WITHPROFITS,
      *                     EQUITIES,
      *                     MANAGEDFUND,
      *                     FUNDNAME,
      *                     TERM,
      *                     SUMASSURED,
      *                     LIFEASSURED    )
      *            VALUES ( :DB2-POLICYNUM-INT,
      *                     :CA-E-WITH-PROFITS,
      *                     :CA-E-EQUITIES,
      *                     :CA-E-MANAGED-FUND,
      *                     :CA-E-FUND-NAME,
      *                     :DB2-E-TERM-SINT,
      *                     :DB2-E-SUMASSURED-INT,
      *                     :CA-E-LIFE-ASSURED )
      *       END-EXEC
              DISPLAY '>>> MOCK INSERT @INSERT-ENDOW: '
                  'TABLE=ENDOWMENT'
              MOVE 0 TO SQLCODE
           END-IF

           IF SQLCODE NOT EQUAL 0
             MOVE '90' TO CA-RETURN-CODE
             PERFORM WRITE-ERROR-MESSAGE
      *      Issue Abend to cause backout of update to Policy table
      *      EXEC CICS ABEND ABCODE('LGSQ') NODUMP END-EXEC
             DISPLAY '>>> MOCK ABEND @INSERT-ENDOW: ' 'ABCODE=LGSQ'
             GOBACK
      *      EXEC CICS RETURN END-EXEC
             DISPLAY '>>> MOCK RETURN @INSERT-ENDOW'
             GOBACK
           END-IF.

           EXIT.

      *================================================================*
      * Issue INSERT on house table using values passed in commarea    *
      *================================================================*
       INSERT-HOUSE.

      *    Move numeric fields to integer format
           MOVE CA-H-VALUE       TO DB2-H-VALUE-INT
           MOVE CA-H-BEDROOMS    TO DB2-H-BEDROOMS-SINT

           MOVE ' INSERT HOUSE ' TO EM-SQLREQ
      *    EXEC SQL
      *      INSERT INTO HOUSE
      *                ( POLICYNUMBER,
      *                  PROPERTYTYPE,
      *                  BEDROOMS,
      *                  VALUE,
      *                  HOUSENAME,
      *                  HOUSENUMBER,
      *                  POSTCODE          )
      *         VALUES ( :DB2-POLICYNUM-INT,
      *                  :CA-H-PROPERTY-TYPE,
      *                  :DB2-H-BEDROOMS-SINT,
      *                  :DB2-H-VALUE-INT,
      *                  :CA-H-HOUSE-NAME,
      *                  :CA-H-HOUSE-NUMBER,
      *                  :CA-H-POSTCODE      )
      *    END-EXEC
           DISPLAY '>>> MOCK INSERT @INSERT-HOUSE: ' 'TABLE=HOUSE'
           MOVE 0 TO SQLCODE

           IF SQLCODE NOT EQUAL 0
             MOVE '90' TO CA-RETURN-CODE
             PERFORM WRITE-ERROR-MESSAGE
      *      Issue Abend to cause backout of update to Policy table
      *      EXEC CICS ABEND ABCODE('LGSQ') NODUMP END-EXEC
             DISPLAY '>>> MOCK ABEND @INSERT-HOUSE: ' 'ABCODE=LGSQ'
             GOBACK
      *      EXEC CICS RETURN END-EXEC
             DISPLAY '>>> MOCK RETURN @INSERT-HOUSE'
             GOBACK
           END-IF.

           EXIT.

      *================================================================*
      * Issue INSERT on motor table using values passed in commarea    *
      *================================================================*
       INSERT-MOTOR.

      *    Move numeric fields to integer format
           MOVE CA-M-VALUE       TO DB2-M-VALUE-INT
           MOVE CA-M-CC          TO DB2-M-CC-SINT
           MOVE CA-M-PREMIUM     TO DB2-M-PREMIUM-INT
           MOVE CA-M-ACCIDENTS   TO DB2-M-ACCIDENTS-INT

           MOVE ' INSERT MOTOR ' TO EM-SQLREQ
      *    EXEC SQL
      *      INSERT INTO MOTOR
      *                ( POLICYNUMBER,
      *                  MAKE,
      *                  MODEL,
      *                  VALUE,
      *                  REGNUMBER,
      *                  COLOUR,
      *                  CC,
      *                  YEAROFMANUFACTURE,
      *                  PREMIUM,
      *                  ACCIDENTS )
      *         VALUES ( :DB2-POLICYNUM-INT,
      *                  :CA-M-MAKE,
      *                  :CA-M-MODEL,
      *                  :DB2-M-VALUE-INT,
      *                  :CA-M-REGNUMBER,
      *                  :CA-M-COLOUR,
      *                  :DB2-M-CC-SINT,
      *                  :CA-M-MANUFACTURED,
      *                  :DB2-M-PREMIUM-INT,
      *                  :DB2-M-ACCIDENTS-INT )
      *    END-EXEC
           DISPLAY '>>> MOCK INSERT @INSERT-MOTOR: ' 'TABLE=MOTOR'
           MOVE 0 TO SQLCODE

           IF SQLCODE NOT EQUAL 0
             MOVE '90' TO CA-RETURN-CODE
             PERFORM WRITE-ERROR-MESSAGE
      *      Issue Abend to cause backout of update to Policy table
      *      EXEC CICS ABEND ABCODE('LGSQ') NODUMP END-EXEC
             DISPLAY '>>> MOCK ABEND @INSERT-MOTOR: ' 'ABCODE=LGSQ'
             GOBACK
      *      EXEC CICS RETURN END-EXEC
             DISPLAY '>>> MOCK RETURN @INSERT-MOTOR'
             GOBACK
           END-IF.

           EXIT.

      *================================================================*
      * Issue INSERT on commercial table with values passed in commarea*
      *================================================================*
       INSERT-COMMERCIAL.

           MOVE CA-B-FirePeril       To DB2-B-FirePeril-Int
           MOVE CA-B-FirePremium     To DB2-B-FirePremium-Int
           MOVE CA-B-CrimePeril      To DB2-B-CrimePeril-Int
           MOVE CA-B-CrimePremium    To DB2-B-CrimePremium-Int
           MOVE CA-B-FloodPeril      To DB2-B-FloodPeril-Int
           MOVE CA-B-FloodPremium    To DB2-B-FloodPremium-Int
           MOVE CA-B-WeatherPeril    To DB2-B-WeatherPeril-Int
           MOVE CA-B-WeatherPremium  To DB2-B-WeatherPremium-Int
           MOVE CA-B-Status          To DB2-B-Status-Int

           MOVE ' INSERT COMMER' TO EM-SQLREQ
      *    EXEC SQL
      *      INSERT INTO COMMERCIAL
      *                (
      *                  PolicyNumber,
      *                  RequestDate,
      *                  StartDate,
      *                  RenewalDate,
      *                  Address,
      *                  Zipcode,
      *                  LatitudeN,
      *                  LongitudeW,
      *                  Customer,
      *                  PropertyType,
      *                  FirePeril,
      *                  FirePremium,
      *                  CrimePeril,
      *                  CrimePremium,
      *                  FloodPeril,
      *                  FloodPremium,
      *                  WeatherPeril,
      *                  WeatherPremium,
      *                  Status,
      *                  RejectionReason
      *                                      )
      *         VALUES (
      *                  :DB2-POLICYNUM-INT,
      *                  :CA-LASTCHANGED,
      *                  :CA-ISSUE-DATE,
      *                  :CA-EXPIRY-DATE,
      *                  :CA-B-Address,
      *                  :CA-B-Postcode,
      *                  :CA-B-Latitude,
      *                  :CA-B-Longitude,
      *                  :CA-B-Customer,
      *                  :CA-B-PropType,
      *                  :DB2-B-FirePeril-Int,
      *                  :DB2-B-FirePremium-Int,
      *                  :DB2-B-CrimePeril-Int,
      *                  :DB2-B-CrimePremium-Int,
      *                  :DB2-B-FloodPeril-Int,
      *                  :DB2-B-FloodPremium-Int,
      *                  :DB2-B-WeatherPeril-Int,
      *                  :DB2-B-WeatherPremium-Int,
      *                  :DB2-B-Status-Int,
      *                  :CA-B-RejectReason
      *                                      )
      *    END-EXEC
           DISPLAY '>>> MOCK INSERT @INSERT-COMMERCIAL: '
               'TABLE=COMMERCIAL'
           MOVE 0 TO SQLCODE

           IF SQLCODE NOT EQUAL 0
             MOVE '90' TO CA-RETURN-CODE
             PERFORM WRITE-ERROR-MESSAGE
      *      Issue Abend to cause backout of update to Policy table
      *      EXEC CICS ABEND ABCODE('LGSQ') NODUMP END-EXEC
             DISPLAY '>>> MOCK ABEND @INSERT-COMMERCIAL: ' 'ABCODE=LGSQ'
             GOBACK
      *      EXEC CICS RETURN END-EXEC
             DISPLAY '>>> MOCK RETURN @INSERT-COMMERCIAL'
             GOBACK
           END-IF.

           EXIT.

      *================================================================*
      * Procedure to write error message to Queues                     *
      *   message will include Date, Time, Program Name, Customer      *
      *   Number, Policy Number and SQLCODE.                           *
      *================================================================*
       WRITE-ERROR-MESSAGE.
      * Save SQLCODE in message
           MOVE SQLCODE TO EM-SQLRC
      * Obtain and format current time and date
      *    EXEC CICS ASKTIME ABSTIME(ABS-TIME)
      *    END-EXEC
           DISPLAY '>>> MOCK ASKTIME @WRITE-ERROR-MESSAGE'
           MOVE 0 TO ABS-TIME
      *    EXEC CICS FORMATTIME ABSTIME(ABS-TIME)
      *              MMDDYYYY(DATE1)
      *              TIME(TIME1)
      *    END-EXEC
           DISPLAY '>>> MOCK FORMATTIME @WRITE-ERROR-MESSAGE'
           MOVE 0 TO ABS-TIME
           MOVE '01012024' TO DATE1
           MOVE '120000' TO TIME1
           MOVE DATE1 TO EM-DATE
           MOVE TIME1 TO EM-TIME
      * Write output message to TDQ
      *    EXEC CICS LINK PROGRAM('LGSTSQ')
      *              COMMAREA(ERROR-MSG)
      *              LENGTH(LENGTH OF ERROR-MSG)
      *    END-EXEC.
           DISPLAY '>>> MOCK LINK @WRITE-ERROR-MESSAGE: ' 'LGSTSQ'.
      * Write 90 bytes or as much as we have of commarea to TDQ
           IF EIBCALEN > 0 THEN
             IF EIBCALEN < 91 THEN
               MOVE DFHCOMMAREA(1:EIBCALEN) TO CA-DATA
      *        EXEC CICS LINK PROGRAM('LGSTSQ')
      *                  COMMAREA(CA-ERROR-MSG)
      *                  LENGTH(LENGTH OF CA-ERROR-MSG)
      *        END-EXEC
               DISPLAY '>>> MOCK LINK @WRITE-ERROR-MESSAGE: ' 'LGSTSQ'
             ELSE
               MOVE DFHCOMMAREA(1:90) TO CA-DATA
      *        EXEC CICS LINK PROGRAM('LGSTSQ')
      *                  COMMAREA(CA-ERROR-MSG)
      *                  LENGTH(LENGTH OF CA-ERROR-MSG)
      *        END-EXEC
               DISPLAY '>>> MOCK LINK @WRITE-ERROR-MESSAGE: ' 'LGSTSQ'
             END-IF
           END-IF.
           EXIT.
