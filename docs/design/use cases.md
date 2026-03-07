# WKM Racing Management System - przypadki użycia

## Definicje ról i pojęć używanych w przypadkach użycia

### Mistrz Ceremonii 
Zazwyczaj organizator spotkania, osoba która nadzoruje sesję treningową i podejmuje decyzje o jej przebiegu

### Sesja Treningowa, Sesja
Spotkanie mające na celu wspólne polatanie dronami. Odbywa się we wspólnym pomieszczeniu, na rozstawionym torze. W ramach sesji, wszyscy aktywni piloci latają na zmianę w czwórkach ustalonych przez system.

### Przelot
Czas przeznaczony na wyłączne latanie jednej Grupy 

### Grupa
Wyznaczona grupa pilotów, zwykle i optymalnie 4 osobowa, która w wyznaczonym momencie dostaje prawo wykonania Przelotu
Grupy są numerowane kolejnymi dodatnimi liczbami naturalnymi. 
W ramach grupy każdemu Pilotowi przydzielany jest kanał video, Unikalny w ramach danej grupy.

### Pilot
Osoba pilotująca pojedynczy statek bezzałogowy i wykopnująca nim przeloty


## Mistrz Ceremonii inicjuje Sesję Treningową

Po rozstawieniu toru, Mistrz Ceremonii inicjuje sesje treningową. Okreśja jej parametr takie jak:
1. Nazwa sesji, data jej odbycia
2. Długość czasu trwania Przelotu oraz czasu na zmianę Grupy 
3. ...

Po wystartowaniu sesji Mistrz identyfikuje aktywnych Pilotów a następnie wpisuje ich do systemu. Jeśli pilot uczestniczył we wcześniejszych treningach, jest wyszukiwany w bazie. Jeśli jest to jego pierwszy raz na treeningach, tworzony jes nowy profil pilota

Po zakończeniu rejestracji pilotów, System prezentuje Mistrzowi propozycję podziału na grupy, dając mu do wyboru albo akceptację, albo ręczno modyfikacje przydziału do grup. 

Po akceptacji grup, system prezentuje aktualną i następną grupę a następnie oczekuje na wydanie przez Mistrza komendy rozpoczęcia cyklu treningowego 


## Cykl treningowy 

Cykl treningowy to automatyczny i bezobsługowy proces przeprowadzania treningu. Polega on na cykliczny wykonywaniu czynności:
1. Wytypowaniu grupy do wykonania Przelotu, oraz następnej grupy do Przelotu 
2. Poinformowaniu członków grupy o rozpoczęciu ich sesji - TBD
3. Odmierzenia czasu na przygotowania - według ustalonej wcześniej konfiguracji
4. Poinformowanie uczestników grupy o rozpoczęciu Przelotu 
5. Odmierzania czasu przelotu 
6. Poinformowaniu o zbliżającym się czasie końca przelotu 
7. Poinformowanie o zakończeniu przelotu

W trakcie cyklu mogą następować zdarzenia opisane w innych przypadkach użycia. Każdy taki przypadek będzie definiował, czy i w jaki sposób wpływa na przebieg cyklu treningowego. 


## Wstrzymanie czasu Przelotu i ewentualne zakończenie aktualnego przelotu
Akcja ta może być wykonana przez Mistrza Ceremonii.
Po wybraniu opcji wstrzymania czasu, następuje zatrzymanie timera odmierzającego czas przelotu. Po zatrzymaniu czasu, Mistrz jest pytany, czy zakończyć aktualny Przelot, czy jedynie go wstrzymać. 

W trakcie, gdy czas jest wstrzymany, Mistrz może dokonać zmian opisanych w innych przypadkach użycia. 

Po zakończeniu innych czynności, Mistrz może wystartować czas kontynnując przerwaną grupę lub wskazując grupę, od któej ma nastąpić wznowienie. 


## Zakończenie Sesji Treningowej 
Mistrz ceremonii decyduje o zakończeniu Sesji Treningowej. Zostaje zakończony aktualny przelot, wszystkie zegary zostają zatrzymane a sesja zostaje oznaczona jako zamknięta. Przechodzi w stan oczekiwania na otwarcie następnej sesji. 

Po zamknięciu sesji, system może wygenerować raport o sesji, zawierające wszystkie zgromadzone w trakcie dane. Raport globalny powinien być wysłany do Mistrza Ceremonii. Indywidualne raporty mogą być wysłane do poszczególnych pilotów. 


## Nowy pilot dołącza do sesji 
Dołączanie nowego pilota nie wstrzymuje cyklu treningowego. 
Dołączenie nowego pilota polega na dodaniu go do listy aktywnych pilotów. Zostaje on dodany do istniejącej grupy, lub tworzona jest dla niego nowa grupa. Polit nie może zostać dodany do grupy aktualnie wykonującej przelot ani do grupy już ogłoszonej jako następna. 

Po dodaniu pilota do grupy, Mistrz ceremonii ma możlość ręcznej zmiany przydziału do grup, przy czym zmiana ta będzie miała skutek dopiero po zakończeniu aktualnego przelotu oraz przelotu grupy ogłoszonej jako następna. 

## Pilot opuszcza sesję treningową
Opuszczenie przez Pilota sesji, nie wtrzymuje cyklu treningowego 

Aktywny pilot decyduje o opuszczeniu sesji i nie będzie już wykonywał przelotów. Po potwierdzeniu jego woli, zostaje on oznaczony jako nieaktywny i usunięty z grupy do której został przydzielony. 

Po usunięciu pilota z grupy, system może podjąć decyzję o re-ballancingu grup, tak aby zoptymalizować dostępny czas. Po rebalansingu  Mistrz Ceremonii ma możlość ręcznej zmiany przydziału do grup. 
Zarówno rebalansing grup jak i ewentualna zmiana ręczna będą miały skutek dopiero po zakończeniu aktualnego przelotu oraz przelotu grupy ogłoszonej jako następna. 

## Uczestnik sesji chce zobaczyć pełny rozkład grup 
Oglądanie pełnego podziału na grupy nie wstrzymuje cyklu sesji treningowej.

W trakcie trwania cyklu, dowolny użytkownik ma możliwość obejrzenia pełnej listy grup. W tym celu na ekranie głównym znajduje się przycisk, wyświetlający nakładkę na ekran z aktualnym widokiem grup. 

Widok grup powiniem mieć możliwość zamknięcia i powrotu do ekranu głównego. Ekran widoku grup powinien samoczynnie się zamykać po określonym czasie - inicjalnie czas ten będzie ustawiony na 20 sekund. 


## Mistrz Ceremonii ręcznie modyfikuje przydział do grup
Modyfikacja grup nie wpływ na trwający cykl

Mistrz ceremonii ma możliwość wyświetlenia i modyfikacji aktualnego przydziały Pilotów do grup. W tym celu będzie mu wyświetlony ekran zawierający:
- Listę grup 
- Listę Pilotów w danej grupie wraz z przydzielonym mu kanałem 
- Listę aktywnych Pilotów, któzy nie mają przydziału do grupy 

W ramach ręcznej edycji przydziału do grup, Mistrz ma możliwość
- Usunięcia pilota z grupy - pilot jest przeniesony do listy pilotów bez przydziału 
- Przydzielenie Pilota bez przydziału do wolnego miejsca w grupie
- Stworzenia nowej grupy 
- Usunięcia grupy. W przypadku kiedy grupa zawiera Pilotów, są oni przenoszeni do listy pilotów bez przydziału 

Mistrz może zakończyć edycję z pilotami bez przydziału.
Po zamknięciu edycji, grupy które są puste, zostają usunięte. 
W trakcie modyfikacji grup, dane są zapisywane natychmiast, bez możliwości ich wycowania, czy wycofania całości zmian. 


## Pilot uruchamia prywatny ekran monitorujący 

Pilot ma możliwość uruchomienia na swoim prywatnym urządzeniu ekranu śledzącego jego osobiste komunikaty. Ekran taki ma różne funkcje w zależności, czy pilot jest w trakcie przelotu czy nie

W trakcie przelotu, ekran komunikuje się  pilotem przekazując mu wiadomości w formie odtwarzanych komunikatac głosowych, które przekazują informacje:
- dźwiękowy sygnał rozpoczęcia przygotowań do przelotu
- dźwiękowy sygnał rozpoczęcia przelotu
- dźwiękowy sygnał zbliżającego się czasu końca przelotu
- dźwiękowy sygnał o zakończeniu przelotu 
- dźwiękowy odczyt z indywidualnego rejestratora czasu przelotu okrążenia

Poza przelotem, indywidualny ekran Pilota podaje mu następujące informacje:
- Aktualny przydział do grupy i przydzielony kanał video 
- Oczekiwany czas do rozpoczęcia następnego przelotu Pilota
- Numer aktualnie latającej grupy i czas przelotu 
- Listę przelotów już odbytych wraz z czasami okrążeń 
- Możliwość opuszczenia Sesji Treningowej 

## Mistrz Ceremonii uruchamia ekran zarządzania Sesją

Mistrz ceremonii ma możliwość uruchmienia na swoim prywatnym urządzeniu ekranu zarządzania sesją. Ma on na niej możliwość wykonania wszelkich czynności administracyjnych, takich jak:
- Rozpoczęcie sesji 
- Wstrzymanie i uruchomienie czasu 
- Dodanie i usunęcie aktywnych pilotów
- Zarządzanie składem grup
- Zakończenie Sesji 

## Przeglądanie raportów osobistych ze wszystkich Sesji Treningowych Pilota 

Pilot ma możliwość oglądania swoich osobistych statystyk z odbytych sesji treningowych. Raporty powinny być dostępne również przy braku aktywnej Sesji Treningowej. Przy przeglądaniu polit ma możliwość obejrzenia:
- Listy Sesji Treningwych w których uczestniczył 
- Czasów przelotów okrążeń w ramach poszczególnych sesji 
- Analiza statystyczna poszczególnych sesji w zakresie czasów przelotów, takich jak średni czas, wariancja
- Analiza porównawcza czasów przelotów Pilota na tle całej grupy trenującej 


