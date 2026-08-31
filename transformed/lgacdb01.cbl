       PROCESS SQL
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2021                             *
      *                                                                *
      *                    ADD Customer Details                        *
      *                                                                *
      *   To add customer's name, address and date of birth to the     *
      *  DB2 customer table creating a new customer entry.             *
      *                                                                *
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LGACDB01.
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
                                        VALUE 'LGACDB01------WS'.
           03 WS-TRANSID               PIC X(4).
           03 WS-TERMID                PIC X(4).
           03 WS-TASKNUM               PIC 9(7).
           03 WS-FILLER                PIC X.
           03 WS-ADDR-DFHCOMMAREA      USAGE is POINTER.
           03 WS-CALEN                 PIC S9(4) COMP.

      *
       01  WS-RESP                   PIC S9(8) COMP.
       01  LastCustNum               PIC S9(8) COMP.
       01  GENAcount                 PIC X(16) Value 'GENACUSTNUM'.
       01  GENApool                  PIC X(8)  Value 'GENA'.
      * Variables for time/date processing
       01  WS-ABSTIME                  PIC S9(8) COMP VALUE +0.
       01  WS-TIME                     PIC X(8)  VALUE SPACES.
       01  WS-DATE                     PIC X(10) VALUE SPACES.

      * Error Message structure
       01  ERROR-MSG.
           03 EM-DATE                  PIC X(8)  VALUE SPACES.
           03 FILLER                   PIC X     VALUE SPACES.
           03 EM-TIME                  PIC X(6)  VALUE SPACES.
           03 FILLER                   PIC X(9)  VALUE ' LGACDB01'.
           03 EM-VARIABLE.
             05 FILLER                 PIC X(6)  VALUE ' CNUM='.
             05 EM-CUSNUM              PIC X(10)  VALUE SPACES.
             05 EM-SQLREQ              PIC X(16) VALUE SPACES.
             05 FILLER                 PIC X(9)  VALUE ' SQLCODE='.
             05 EM-SQLRC               PIC +9(5) USAGE DISPLAY.

       01  CDB2AREA.
           03 D2-REQUEST-ID            PIC X(6).
           03 D2-RETURN-CODE           PIC 9(2).
           03 D2-CUSTOMER-NUM          PIC 9(10).
           03 D2-CUSTSECR-PASS         PIC X(32).
           03 D2-CUSTSECR-COUNT        PIC X(4).
           03 D2-CUSTSECR-STATE        PIC X.
           03 D2-CUSTSECR-DATA         PIC X(32445).

       01  CA-ERROR-MSG.
           03 FILLER                   PIC X(9)  VALUE 'COMMAREA='.
           03 CA-DATA                  PIC X(90) VALUE SPACES.
      *----------------------------------------------------------------*
       77 LGACDB02                     PIC X(8)  VALUE 'LGACDB02'.
       77 LGACVS01                     PIC X(8)  VALUE 'LGACVS01'.
       77 LGAC-NCS                     PIC X(2)  VALUE 'ON'.
       77 WS-CS-PASSWORD               PIC X(16) Value 'NewPass'.
       77 WS-CS-STATE                  PIC X     VALUE 'N'.
       77 WS-CA-COUNT                  PIC S9(9) COMP  Value 0.

      *----------------------------------------------------------------*
      * Definitions required for data manipulation                     *
      *----------------------------------------------------------------*
      * Fields to be used to check that commarea is correct length
       01  WS-COMMAREA-LENGTHS.
           03 WS-CA-HEADER-LEN         PIC S9(4) COMP VALUE +18.
           03 WS-REQUIRED-CA-LEN       PIC S9(4)      VALUE +0.


      *    Include copybook for defintion of customer details length
      * >>> BEGIN COPY LGPOLICY (LGPOLICY.cpy)
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
      * <<< END COPY LGPOLICY
      *----------------------------------------------------------------*

      *----------------------------------------------------------------*
      * Definitions required by SQL statement                          *
      *   DB2 datatypes to COBOL equivalents                           *
      *     SMALLINT    :   PIC S9(4) COMP                             *
      *     INTEGER     :   PIC S9(9) COMP                             *
      *     DATE        :   PIC X(10)                                  *
      *     TIMESTAMP   :   PIC X(26)                                  *
      *----------------------------------------------------------------*
      * Host variables for output from DB2 integer types
       01  DB2-OUT-INTEGERS.
           03 DB2-CUSTOMERNUM-INT   PIC S9(9) COMP.
      *----------------------------------------------------------------*

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

      *----------------------------------------------------------------*
      * Common code                                                    *
      *----------------------------------------------------------------*
      * initialize working storage variables
           INITIALIZE WS-HEADER.
      * set up general variable
           MOVE EIBTRNID TO WS-TRANSID.
           MOVE EIBTRMID TO WS-TERMID.
           MOVE EIBTASKN TO WS-TASKNUM.
      *----------------------------------------------------------------*


      * initialize DB2 host variables
           INITIALIZE DB2-OUT-INTEGERS.

      *----------------------------------------------------------------*
      * Process incoming commarea                                      *
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
           MOVE EIBCALEN TO WS-CALEN.
           SET WS-ADDR-DFHCOMMAREA TO ADDRESS OF DFHCOMMAREA.

      * check commarea length
           ADD WS-CA-HEADER-LEN TO WS-REQUIRED-CA-LEN
           ADD WS-CUSTOMER-LEN  TO WS-REQUIRED-CA-LEN

      * if less set error return code and return to caller
           IF EIBCALEN IS LESS THAN WS-REQUIRED-CA-LEN
             MOVE '98' TO CA-RETURN-CODE
      *      EXEC CICS RETURN END-EXEC
             DISPLAY '>>> MOCK RETURN @MAINLINE'
             GOBACK
           END-IF

      * Call routine to Insert row in Customer table                   *
           PERFORM Obtain-CUSTOMER-Number.
           PERFORM INSERT-CUSTOMER.

      *    EXEC CICS LINK Program(LGACVS01)
      *         Commarea(DFHCOMMAREA)
      *         LENGTH(225)
      *    END-EXEC.
           DISPLAY '>>> MOCK LINK @MAINLINE: ' 'LGACVS01'.

           MOVE DB2-CUSTOMERNUM-INT TO D2-CUSTOMER-NUM.
           Move '02ACUS'     To  D2-REQUEST-ID.
           move '5732fec825535eeafb8fac50fee3a8aa'
                             To  D2-CUSTSECR-PASS.
           Move '0000'       To  D2-CUSTSECR-COUNT.
           Move 'N'          To  D2-CUSTSECR-STATE.

      *    EXEC CICS LINK Program(LGACDB02)
      *         Commarea(CDB2AREA)
      *         LENGTH(32500)
      *    END-EXEC.
           DISPLAY '>>> MOCK LINK @MAINLINE: ' 'LGACDB02'.

      *    Return to caller
      *    EXEC CICS RETURN END-EXEC.
           DISPLAY '>>> MOCK RETURN @MAINLINE'
           GOBACK.

       MAINLINE-EXIT.
           EXIT.
      *----------------------------------------------------------------*


       Obtain-CUSTOMER-Number.

      *    Exec CICS Get Counter(GENAcount)
      *                  Pool(GENApool)
      *                  Value(LastCustNum)
      *                  Resp(WS-RESP)
      *    End-Exec.
           DISPLAY '>>> MOCK GET COUNTER @OBTAIN-CUSTOMER-NUMBER: '
               GENAcount
           MOVE 1 TO LastCustNum
           MOVE 0 TO WS-RESP.
           If WS-RESP Not = 0
             MOVE 'NO' TO LGAC-NCS
             Initialize DB2-CUSTOMERNUM-INT
           ELSE
             Move LastCustNum  To DB2-CUSTOMERNUM-INT
           End-If.


      *================================================================*
       INSERT-CUSTOMER.
      *================================================================*
      * Insert row into Customer table based on customer number        *
      *================================================================*
           MOVE ' INSERT CUSTOMER' TO EM-SQLREQ
      *================================================================*
           IF LGAC-NCS = 'ON'
      *      EXEC SQL
      *        INSERT INTO CUSTOMER
      *                  ( CUSTOMERNUMBER,
      *                    FIRSTNAME,
      *                    LASTNAME,
      *                    DATEOFBIRTH,
      *                    HOUSENAME,
      *                    HOUSENUMBER,
      *                    POSTCODE,
      *                    PHONEMOBILE,
      *                    PHONEHOME,
      *                    EMAILADDRESS )
      *           VALUES ( :DB2-CUSTOMERNUM-INT,
      *                    :CA-FIRST-NAME,
      *                    :CA-LAST-NAME,
      *                    :CA-DOB,
      *                    :CA-HOUSE-NAME,
      *                    :CA-HOUSE-NUM,
      *                    :CA-POSTCODE,
      *                    :CA-PHONE-MOBILE,
      *                    :CA-PHONE-HOME,
      *                    :CA-EMAIL-ADDRESS )
      *      END-EXEC
             DISPLAY '>>> MOCK INSERT @INSERT-CUSTOMER: '
                 'TABLE=CUSTOMER'
             MOVE 0 TO SQLCODE
             IF SQLCODE NOT EQUAL 0
               MOVE '90' TO CA-RETURN-CODE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @INSERT-CUSTOMER'
               GOBACK
             END-IF
           ELSE
      *      EXEC SQL
      *        INSERT INTO CUSTOMER
      *                  ( CUSTOMERNUMBER,
      *                    FIRSTNAME,
      *                    LASTNAME,
      *                    DATEOFBIRTH,
      *                    HOUSENAME,
      *                    HOUSENUMBER,
      *                    POSTCODE,
      *                    PHONEMOBILE,
      *                    PHONEHOME,
      *                    EMAILADDRESS )
      *           VALUES ( DEFAULT,
      *                    :CA-FIRST-NAME,
      *                    :CA-LAST-NAME,
      *                    :CA-DOB,
      *                    :CA-HOUSE-NAME,
      *                    :CA-HOUSE-NUM,
      *                    :CA-POSTCODE,
      *                    :CA-PHONE-MOBILE,
      *                    :CA-PHONE-HOME,
      *                    :CA-EMAIL-ADDRESS )
      *      END-EXEC
             DISPLAY '>>> MOCK INSERT @INSERT-CUSTOMER: '
                 'TABLE=CUSTOMER'
             MOVE 0 TO SQLCODE
             IF SQLCODE NOT EQUAL 0
               MOVE '90' TO CA-RETURN-CODE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @INSERT-CUSTOMER'
               GOBACK
             END-IF
      *    get value of assigned customer number
      *        EXEC SQL
      *          SET :DB2-CUSTOMERNUM-INT = IDENTITY_VAL_LOCAL()
      *        END-EXEC
               DISPLAY '>>> MOCK SET @INSERT-CUSTOMER'
               MOVE 1 TO DB2-CUSTOMERNUM-INT
               MOVE 0 TO SQLCODE
           END-IF.

           MOVE DB2-CUSTOMERNUM-INT TO CA-CUSTOMER-NUM.

           EXIT.
      *================================================================*

      *================================================================*
      * Procedure to write error message to Queues                     *
      *   message will include Date, Time, Program Name, Customer      *
      *   Number, Policy Number and SQLCODE.                           *
      *================================================================*
       WRITE-ERROR-MESSAGE.
      * Save SQLCODE in message
           MOVE SQLCODE TO EM-SQLRC
      * Obtain and format current time and date
      *    EXEC CICS ASKTIME ABSTIME(WS-ABSTIME)
      *    END-EXEC
           DISPLAY '>>> MOCK ASKTIME @WRITE-ERROR-MESSAGE'
           MOVE 0 TO WS-ABSTIME
      *    EXEC CICS FORMATTIME ABSTIME(WS-ABSTIME)
      *              MMDDYYYY(WS-DATE)
      *              TIME(WS-TIME)
      *    END-EXEC
           DISPLAY '>>> MOCK FORMATTIME @WRITE-ERROR-MESSAGE'
           MOVE 0 TO WS-ABSTIME
           MOVE '01012024' TO WS-DATE
           MOVE '120000' TO WS-TIME
           MOVE WS-DATE TO EM-DATE
           MOVE WS-TIME TO EM-TIME
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
