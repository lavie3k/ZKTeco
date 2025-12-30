## ZKTeco

#### [Vuln 1] Default-password in ZKTeco F18

On some models, the Time-Based Reset method can be used to reset the Administrator password of a ZKTeco fingerprint device.

Please follow the step-by-step instructions below to unlock a ZKTeco fingerprint access control device using the Time-Based method to access the menu and clear the administrator password.

On the main screen, check the current time displayed on the device.

Use a calculator and subtract the displayed time from 9999.

For example, if the time shown is 13:37, calculate:
9999 − 1337 = 8662

Then multiply the result by itself:
8662 × 8662 = 75030244

The resulting number (75030244) is the Super Password.

On the fingerprint device, press the Menu button.

Enter 8888.

Press OK.

Enter the Super Password, then press OK.

You will now be able to access the menu and clear the administrator password.

#### [Vuln 2] RCE via USB

- https://www.synacktiv.com/advisories/vulnerable-upgrade-mechanism-in-zkteco-f18-device
