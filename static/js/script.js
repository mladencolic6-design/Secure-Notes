let video;
let canvas;
let nameInput;
let statusBox;

function setStatus(message) {
    statusBox.textContent = message;
}

function init() {
    video = document.getElementById("video");
    canvas = document.getElementById("canvas");
    nameInput = document.getElementById("name");
    statusBox = document.getElementById("statusBox");

    navigator.mediaDevices.getUserMedia({ video: true })
        .then(stream => {
            video.srcObject = stream;
            video.play();
            setStatus("Camera a fost pornită cu succes. Poți face captură, înregistrare sau autentificare.");
        })
        .catch(error => {
            console.log("error access webcam", error);
            setStatus("Camera nu este disponibilă. Verifică permisiunile browserului.");
            alert("Nu se poate accesa camera web.");
        });
}

function capture() {
    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.style.display = "block";
    console.log("Captured frame", canvas.width, canvas.height);
    setStatus("Fotografia a fost capturată. Acum poți să apeși pe Înregistrare sau Autentificare.");
}

function canvasToBlob() {
    return new Promise((resolve) => {
        canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.95);
    });
}

async function register() {
    const name = nameInput.value.trim();
    capture();

    if (!name) {
        alert("Numele este obligatoriu.");
        return;
    }

    const photo = await canvasToBlob();
    if (!photo) {
        alert("Fotografia este obligatorie.");
        return;
    }

    const formData = new FormData();
    formData.append("name", name);
    formData.append("photo", photo, `${name}.jpg`);

    fetch("/register", {
        method: "POST",
        body: formData
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                setStatus(data.message);
                alert(data.message);
            } else {
                setStatus(data.message || "Înregistrarea a eșuat.");
                alert(data.message || "Înregistrarea a eșuat.");
            }
        })
        .catch(error => {
            console.log("error", error);
            setStatus("A apărut o eroare la înregistrare.");
            alert("Eroare la înregistrare.");
        });
}

async function login() {
    capture();

    const photo = await canvasToBlob();
    if (!photo) {
        alert("Fotografia este obligatorie.");
        return;
    }

    const formData = new FormData();
    formData.append("photo", photo, "login.jpg");

    fetch("/login", {
        method: "POST",
        body: formData
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                setStatus(data.message);
                if (data.redirect_url) {
                    window.location.href = data.redirect_url;
                    return;
                }
                alert(data.message || "Autentificare reușită.");
            } else {
                setStatus(data.message || "Autentificarea a eșuat.");
                alert(data.message || "Autentificarea a eșuat.");
            }
        })
        .catch(error => {
            console.log("error", error);
            setStatus("A apărut o eroare la încercarea de autentificare.");
            alert("Eroare la autentificare.");
        });
}

document.addEventListener("DOMContentLoaded", init);